"""Read-only and opt-in write checks for a local fiscal installation."""

from __future__ import annotations

import hashlib
import stat
from collections.abc import Callable
from pathlib import Path
from uuid import uuid4

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

from apps.certificates.services.upload_envelope import (
    CertificateUploadEnvelope,
    CertificateUploadEnvelopeError,
)
from apps.certificates.services.vault import CertificateVault, CertificateVaultError
from apps.fiscal.services.storage import FiscalStorage, FiscalStorageError


class FiscalPreflightError(ValueError):
    """A non-secret prerequisite for controlled fiscal operation is missing."""


class Command(BaseCommand):
    help = (
        "Verify local fiscal prerequisites without contacting the SEFAZ. "
        "Use --worker and --write-notes-probe in the worker container."
    )

    def add_arguments(self, parser):  # type: ignore[no-untyped-def]
        parser.add_argument(
            "--worker",
            action="store_true",
            help="Also verify worker-only certificate secrets and their key pair.",
        )
        parser.add_argument(
            "--write-notes-probe",
            action="store_true",
            help="Atomically write and remove a harmless probe in the notes volume.",
        )

    def handle(self, *args, **options):  # type: ignore[no-untyped-def]
        failures: list[str] = []
        checks: list[tuple[str, Callable[[], str]]] = [
            ("Banco de dados", self._check_database),
            ("Migrations", self._check_migrations),
            ("Schemas fiscais", self._check_schemas),
            ("Ambientes SEFAZ liberados", self._check_enabled_environments),
            ("Volume de notas", self._check_notes_readable),
            ("Chave pública de upload", self._check_upload_public_key),
        ]
        if options["worker"]:
            checks.extend(
                [
                    ("Chave do cofre", self._check_vault_key),
                    ("Par de chaves de upload", self._check_upload_keypair),
                ]
            )
        if options["write_notes_probe"]:
            checks.append(("Escrita atômica no volume", self._check_notes_write))

        for label, check in checks:
            self._run_check(label=label, check=check, failures=failures)

        if failures:
            raise CommandError(
                "A pré-validação fiscal falhou; corrija os itens acima antes de "
                "qualquer homologação."
            )
        self.stdout.write(
            self.style.SUCCESS(
                "Pré-validação concluída sem contato com a SEFAZ."
            )
        )

    def _run_check(
        self,
        *,
        label: str,
        check: Callable[[], str],
        failures: list[str],
    ) -> None:
        try:
            detail = check()
        except FiscalPreflightError as error:
            failures.append(label)
            self.stderr.write(self.style.ERROR(f"[falhou] {label}: {error}"))
        else:
            self.stdout.write(self.style.SUCCESS(f"[ok] {label}: {detail}"))

    @staticmethod
    def _check_database() -> str:
        try:
            connection.ensure_connection()
        except Exception as error:
            raise FiscalPreflightError("a conexão não está disponível") from error
        return "conexão disponível"

    @staticmethod
    def _check_migrations() -> str:
        try:
            executor = MigrationExecutor(connection)
            plan = executor.migration_plan(executor.loader.graph.leaf_nodes())
        except Exception as error:
            raise FiscalPreflightError(
                "não foi possível inspecionar migrations"
            ) from error
        if plan:
            raise FiscalPreflightError(f"há {len(plan)} migration(s) pendente(s)")
        return "nenhuma pendência"

    @staticmethod
    def _check_schemas() -> str:
        root = settings.FISCAL_SCHEMA_ROOT
        manifest = root / "SHA256SUMS"
        try:
            entries = _manifest_entries(manifest)
            targets: set[Path] = set()
            for expected_hash, relative_path in entries:
                target = _manifest_target(root, relative_path)
                targets.add(target)
                observed_hash = _sha256(target)
                if observed_hash != expected_hash:
                    raise FiscalPreflightError("o checksum de um schema não confere")
            if targets != set(root.resolve().rglob("*.xsd")):
                raise FiscalPreflightError(
                    "o manifesto não corresponde aos schemas versionados"
                )
        except (OSError, UnicodeError) as error:
            raise FiscalPreflightError(
                "os schemas locais não estão acessíveis"
            ) from error
        return f"{len(entries)} arquivo(s) conferido(s)"

    @staticmethod
    def _check_enabled_environments() -> str:
        allowed = settings.SEFAZ_ENABLED_ENVIRONMENTS
        invalid = allowed.difference({"homologation", "production"})
        if invalid:
            raise FiscalPreflightError(
                "há ambiente(s) desconhecido(s) na configuração de liberação"
            )
        if not allowed:
            return "nenhum; tráfego fiscal permanece bloqueado"
        return ", ".join(sorted(allowed))

    @staticmethod
    def _check_notes_readable() -> str:
        root = settings.FISCAL_NOTES_ROOT
        if not root.is_dir():
            raise FiscalPreflightError("o volume configurado não é um diretório")
        try:
            next(root.iterdir(), None)
        except OSError as error:
            raise FiscalPreflightError("o volume não pode ser lido") from error
        return "diretório acessível"

    @staticmethod
    def _check_upload_public_key() -> str:
        try:
            CertificateUploadEnvelope().encrypt(
                b"preflight",
                request_id=uuid4(),
                purpose="preflight",
            )
        except CertificateUploadEnvelopeError as error:
            raise FiscalPreflightError(
                "a chave pública de upload não está disponível ou é inválida"
            ) from error
        return "válida"

    @staticmethod
    def _check_vault_key() -> str:
        vault = CertificateVault()
        storage_id = f"preflight-{uuid4()}"
        try:
            _require_private_file(vault.key_file)
            encrypted = vault.seal(b"preflight", storage_id)
            if vault.unseal(encrypted, storage_id) != b"preflight":
                raise CertificateVaultError("vault probe could not be verified")
        except CertificateVaultError as error:
            raise FiscalPreflightError(
                "a chave privada do cofre não está disponível ou é inválida"
            ) from error
        return "cifra autenticada validada"

    @staticmethod
    def _check_upload_keypair() -> str:
        envelope = CertificateUploadEnvelope()
        request_id = uuid4()
        try:
            _require_private_file(envelope.private_key_file)
            encrypted = envelope.encrypt(
                b"preflight",
                request_id=request_id,
                purpose="preflight",
            )
            if (
                envelope.decrypt(
                    encrypted,
                    request_id=request_id,
                    purpose="preflight",
                )
                != b"preflight"
            ):
                raise CertificateUploadEnvelopeError("upload keypair probe failed")
        except CertificateUploadEnvelopeError as error:
            raise FiscalPreflightError(
                "o par de chaves de upload não está disponível ou não corresponde"
            ) from error
        return "par correspondente"

    @staticmethod
    def _check_notes_write() -> str:
        try:
            FiscalStorage().probe_writable()
        except FiscalStorageError as error:
            raise FiscalPreflightError(
                "a escrita atômica no volume não foi concluída"
            ) from error
        return "sonda gravada e removida"


def _manifest_entries(manifest: Path) -> list[tuple[str, Path]]:
    entries: list[tuple[str, Path]] = []
    for line in manifest.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            expected_hash, relative_name = line.split(maxsplit=1)
        except ValueError as error:
            raise FiscalPreflightError("o manifesto de schemas é inválido") from error
        relative_path = Path(relative_name)
        if (
            len(expected_hash) != 64
            or not all(character in "0123456789abcdef" for character in expected_hash)
            or relative_path.is_absolute()
            or ".." in relative_path.parts
        ):
            raise FiscalPreflightError("o manifesto de schemas é inválido")
        entries.append((expected_hash, relative_path))
    if not entries:
        raise FiscalPreflightError("o manifesto de schemas está vazio")
    return entries


def _manifest_target(root: Path, relative_path: Path) -> Path:
    target = (root / relative_path).resolve()
    if root.resolve() not in target.parents or not target.is_file():
        raise FiscalPreflightError("um schema declarado no manifesto está ausente")
    return target


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as schema_file:
        for chunk in iter(lambda: schema_file.read(64 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _require_private_file(path: Path) -> None:
    try:
        mode = stat.S_IMODE(path.stat().st_mode)
    except OSError as error:
        raise FiscalPreflightError(
            "um arquivo privado obrigatório está ausente"
        ) from error
    if mode & 0o077:
        raise FiscalPreflightError(
            "um arquivo privado tem permissões de grupo ou outros"
        )
