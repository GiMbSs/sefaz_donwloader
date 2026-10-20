"""Verify candidate bindings before repairing stale encrypted-vault metadata."""

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

from cryptography.hazmat.primitives.serialization import pkcs12
from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import check_password
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.utils import timezone

from apps.certificates.models import DigitalCertificate
from apps.operations.models import AuditLog
from apps.organizations.access import manageable_companies
from apps.organizations.storage import company_storage_directory

from .identity import certificate_cnpj
from .vault import CertificateVault, CertificateVaultError, inspect_pkcs12


@dataclass(frozen=True)
class VaultBindingReport:
    state: str
    candidates: tuple[UUID, ...] = ()


def _verified_candidate(
    certificate: DigitalCertificate, vault: CertificateVault, path: Path
) -> tuple[UUID, str, str] | None:
    try:
        sid = UUID(path.name.removesuffix(".pfx.enc"))
        password_path = path.with_name(f"{sid}.password.enc")
        vault._resolve_path(password_path.relative_to(vault.root).as_posix())
        payload = vault.unseal(path.read_bytes(), sid, purpose="pfx")
        password = vault.unseal(
            password_path.read_bytes(), sid, purpose="password"
        ).decode("utf-8")
        if not check_password(password, certificate.password_hash):
            return None
        metadata = inspect_pkcs12(payload, password)
        _, public, _ = pkcs12.load_key_and_certificates(payload, password.encode())
        if (
            public is None
            or certificate_cnpj(public) != certificate.company.tax_identifier
            or metadata.fingerprint_sha256 != certificate.certificate_fingerprint_sha256
            or hashlib.sha256(payload).hexdigest() != certificate.content_sha256
            or not metadata.not_valid_before
            <= timezone.now()
            <= metadata.not_valid_after
        ):
            return None
        return (
            sid,
            path.relative_to(vault.root).as_posix(),
            password_path.relative_to(vault.root).as_posix(),
        )
    except (OSError, ValueError, UnicodeError, CertificateVaultError):
        return None


def _candidates(certificate: DigitalCertificate, vault: CertificateVault) -> Any:
    folders = [
        vault.root / company_storage_directory(certificate.company) / "certificado",
        vault.root / "clientes" / str(certificate.company_id) / "certificados",
    ]
    return [
        candidate
        for folder in folders
        if folder.is_dir()
        for path in folder.glob("*.pfx.enc")
        if vault.root.resolve() in path.resolve().parents
        if (candidate := _verified_candidate(certificate, vault, path)) is not None
    ]


def inspect_vault_binding(certificate_id: int) -> VaultBindingReport:
    certificate = DigitalCertificate.objects.select_related("company__office").get(
        pk=certificate_id
    )
    vault = CertificateVault()
    candidates = _candidates(certificate, vault)
    if len(candidates) > 1:
        return VaultBindingReport("ambiguous", tuple(item[0] for item in candidates))
    if candidates:
        return VaultBindingReport("matched", (candidates[0][0],))
    exists = any(vault.root.glob("**/*.pfx.enc")) if vault.root.exists() else False
    return VaultBindingReport("divergent" if exists else "missing")


@transaction.atomic
def apply_verified_binding(
    certificate_id: int, candidate_storage_id: UUID, *, actor_id: int
) -> None:
    certificate = (
        DigitalCertificate.objects.select_for_update()
        .select_related("company__office")
        .get(pk=certificate_id, status=DigitalCertificate.Status.ACTIVE)
    )
    actor = get_user_model().objects.get(pk=actor_id)
    if (
        not actor.is_active
        or not manageable_companies(actor).filter(pk=certificate.company_id).exists()
    ):
        raise PermissionDenied("Apenas administradores podem reconciliar o cofre.")
    candidates = _candidates(certificate, CertificateVault())
    if len(candidates) != 1 or candidates[0][0] != candidate_storage_id:
        raise CertificateVaultError("Nenhum vínculo único comprovado para este A1.")
    old_id = str(certificate.storage_id)
    (
        certificate.storage_id,
        certificate.encrypted_path,
        certificate.encrypted_password_path,
    ) = candidates[0]
    certificate.save(
        update_fields=["storage_id", "encrypted_path", "encrypted_password_path"]
    )
    AuditLog.objects.create(
        actor_id=actor_id,
        action="certificates.vault_binding_reconciled",
        target=f"certificate:{certificate.pk}",
        payload={
            "previous_storage_id": old_id,
            "storage_id": str(certificate.storage_id),
        },
    )
