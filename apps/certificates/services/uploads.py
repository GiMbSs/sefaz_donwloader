"""Short-lived, encrypted certificate-upload workflow owned by the worker."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.certificates.models import CertificateUpload, DigitalCertificate
from apps.certificates.services.upload_envelope import (
    CertificateUploadEnvelope,
    CertificateUploadEnvelopeError,
)
from apps.certificates.services.vault import (
    CertificateValidationError,
    CertificateVault,
    CertificateVaultError,
    register_certificate,
)
from apps.operations.models import AuditLog
from apps.organizations.models import ClientCompany

if TYPE_CHECKING:
    from apps.accounts.models import User


class CertificateUploadError(ValueError):
    """The web request cannot create a safe certificate-upload envelope."""


@dataclass(frozen=True)
class CertificateUploadSubmission:
    upload: CertificateUpload
    created: bool


def stage_certificate_upload(
    *,
    company_id: int,
    filename: str,
    payload: bytes,
    password: str,
    uploaded_by: User,
    envelope: CertificateUploadEnvelope | None = None,
    now: datetime | None = None,
    dispatch: bool = True,
) -> CertificateUploadSubmission:
    """Encrypt certificate material with the worker public key and queue it."""
    _validate_upload(filename=filename, payload=payload, password=password)
    now = now or timezone.now()
    envelope = envelope or CertificateUploadEnvelope()
    with transaction.atomic():
        company = (
            ClientCompany.objects.select_for_update().filter(pk=company_id).first()
        )
        if company is None:
            raise CertificateUploadError("Empresa cliente não encontrada.")
        active_upload = (
            CertificateUpload.objects.select_for_update()
            .filter(
                company=company,
                status__in=(
                    CertificateUpload.Status.SUBMITTED,
                    CertificateUpload.Status.PROCESSING,
                ),
            )
            .order_by("created_at")
            .first()
        )
        if active_upload is not None:
            if dispatch and active_upload.status == CertificateUpload.Status.SUBMITTED:
                # A worker can stop after the encrypted envelope is committed.
                # Republishing the same id is safe: the worker claims it under
                # a row lock and never decrypts a second certificate payload.
                transaction.on_commit(_dispatch_upload_processing(active_upload.pk))
            return CertificateUploadSubmission(upload=active_upload, created=False)

        upload = CertificateUpload(
            company=company,
            filename=Path(filename).name,
            uploaded_by=uploaded_by,
            expires_at=now
            + timedelta(seconds=settings.CERTIFICATE_UPLOAD_STAGING_SECONDS),
        )
        try:
            upload.encrypted_payload = envelope.encrypt(
                payload,
                request_id=upload.request_id,
                purpose="pfx",
            )
            upload.encrypted_password = envelope.encrypt(
                password.encode("utf-8"),
                request_id=upload.request_id,
                purpose="password",
            )
        except CertificateUploadEnvelopeError as error:
            if getattr(settings, "DEV_MODE", False):
                message = (
                    "O cofre local de certificados ainda não foi inicializado. "
                    "Execute `python manage.py generate_certificate_key --if-missing` "
                    "e `python manage.py generate_certificate_upload_keypair "
                    "--if-missing`, depois envie o arquivo novamente."
                )
            else:
                message = (
                    "A chave pública do processamento de certificados não está "
                    "disponível."
                )
            raise CertificateUploadError(
                message
            ) from error
        upload.save()
        AuditLog.objects.create(
            actor=uploaded_by,
            action="certificates.upload_staged",
            target=f"certificates.upload:{upload.pk}",
            payload={"company_id": company.pk},
        )
        if dispatch:
            transaction.on_commit(_dispatch_upload_processing(upload.pk))
        return CertificateUploadSubmission(upload=upload, created=True)


def process_certificate_upload(
    upload_id: int,
    *,
    envelope: CertificateUploadEnvelope | None = None,
    vault: CertificateVault | None = None,
    now: datetime | None = None,
) -> str:
    """Decrypt and register one staged upload in the worker process only."""
    now = now or timezone.now()
    with transaction.atomic():
        upload = (
            CertificateUpload.objects.select_for_update()
            .select_related("company")
            .filter(pk=upload_id)
            .first()
        )
        if upload is None:
            return "missing"
        if upload.status in {
            CertificateUpload.Status.COMPLETED,
            CertificateUpload.Status.FAILED,
            CertificateUpload.Status.EXPIRED,
        }:
            return upload.status
        if upload.expires_at <= now:
            _discard_upload(upload, status=CertificateUpload.Status.EXPIRED, now=now)
            return CertificateUpload.Status.EXPIRED
        if upload.status == CertificateUpload.Status.PROCESSING:
            return CertificateUpload.Status.PROCESSING
        if upload.encrypted_payload is None or upload.encrypted_password is None:
            _discard_upload(upload, status=CertificateUpload.Status.FAILED, now=now)
            return CertificateUpload.Status.FAILED
        encrypted_payload = bytes(upload.encrypted_payload)
        encrypted_password = bytes(upload.encrypted_password)
        request_id = upload.request_id
        filename = upload.filename
        company = upload.company
        uploaded_by = upload.uploaded_by
        upload.status = CertificateUpload.Status.PROCESSING
        upload.started_at = now
        upload.save(update_fields=("status", "started_at"))

    envelope = envelope or CertificateUploadEnvelope()
    vault = vault or CertificateVault()
    certificate: DigitalCertificate | None = None
    try:
        payload = envelope.decrypt(
            encrypted_payload,
            request_id=request_id,
            purpose="pfx",
        )
        password = envelope.decrypt(
            encrypted_password,
            request_id=request_id,
            purpose="password",
        ).decode("utf-8")
        with transaction.atomic():
            certificate = register_certificate(
                company=company,
                filename=filename,
                payload=payload,
                password=password,
                uploaded_by=uploaded_by,
                vault=vault,
            )
            upload = CertificateUpload.objects.select_for_update().get(pk=upload_id)
            if upload.status != CertificateUpload.Status.PROCESSING:
                raise CertificateUploadError(
                    "Certificate upload is no longer available."
                )
            upload.status = CertificateUpload.Status.COMPLETED
            upload.certificate = certificate
            upload.encrypted_payload = None
            upload.encrypted_password = None
            upload.error_message = ""
            upload.processed_at = timezone.now()
            upload.save(
                update_fields=(
                    "status",
                    "certificate",
                    "encrypted_payload",
                    "encrypted_password",
                    "error_message",
                    "processed_at",
                )
            )
            AuditLog.objects.create(
                actor=uploaded_by,
                action="certificates.upload_completed",
                target=f"certificates.upload:{upload.pk}",
                payload={"company_id": company.pk, "certificate_id": certificate.pk},
            )
    except CertificateValidationError:
        if certificate is not None:
            try:
                vault.remove(certificate)
            except CertificateVaultError:
                pass
        _mark_upload_failed(
            upload_id,
            now=timezone.now(),
            message="Não foi possível validar o certificado ou a senha informada.",
        )
        return CertificateUpload.Status.FAILED
    except (CertificateUploadEnvelopeError, CertificateVaultError, UnicodeDecodeError):
        if certificate is not None:
            try:
                vault.remove(certificate)
            except CertificateVaultError:
                pass
        _mark_upload_failed(
            upload_id,
            now=timezone.now(),
            message=(
                "O worker não conseguiu processar o envio com segurança. "
                "Tente novamente."
            ),
        )
        return CertificateUpload.Status.FAILED
    except Exception:
        if certificate is not None:
            try:
                vault.remove(certificate)
            except CertificateVaultError:
                pass
        _mark_upload_failed(
            upload_id,
            now=timezone.now(),
            message="O processamento do certificado falhou. Envie o arquivo novamente.",
        )
        return CertificateUpload.Status.FAILED
    finally:
        encrypted_payload = b""
        encrypted_password = b""
        if "payload" in locals():
            payload = b""
        if "password" in locals():
            password = ""
    return CertificateUpload.Status.COMPLETED


def expire_staged_certificate_uploads(*, now: datetime | None = None) -> int:
    """Erase encrypted upload envelopes that were not completed in time."""
    now = now or timezone.now()
    expired = 0
    with transaction.atomic():
        uploads = list(
            CertificateUpload.objects.select_for_update()
            .filter(
                status__in=(
                    CertificateUpload.Status.SUBMITTED,
                    CertificateUpload.Status.PROCESSING,
                ),
                expires_at__lte=now,
            )
            .select_related("company")
        )
        for upload in uploads:
            _discard_upload(upload, status=CertificateUpload.Status.EXPIRED, now=now)
            expired += 1
    return expired


def _validate_upload(*, filename: str, payload: bytes, password: str) -> None:
    validate_certificate_upload_metadata(
        filename=filename,
        payload_size=len(payload),
        password=password,
    )
    if not payload:
        raise CertificateUploadError("O arquivo do certificado está vazio.")


def validate_certificate_upload_metadata(
    *,
    filename: str,
    payload_size: int,
    password: str,
) -> None:
    suffix = Path(filename).suffix.lower()
    if suffix not in {".pfx", ".p12"}:
        raise CertificateUploadError(
            "Envie um certificado A1 nos formatos .pfx ou .p12."
        )
    if payload_size <= 0:
        raise CertificateUploadError("O arquivo do certificado está vazio.")
    if payload_size > settings.CERTIFICATE_MAX_UPLOAD_BYTES:
        raise CertificateUploadError(
            "O arquivo do certificado excede o tamanho permitido."
        )
    if not password:
        raise CertificateUploadError("Informe a senha do certificado.")
    if len(password) > 1024:
        raise CertificateUploadError(
            "A senha do certificado excede o tamanho permitido."
        )


def _dispatch_upload_processing(upload_id: int) -> Callable[[], None]:
    def dispatch() -> None:
        if getattr(settings, "DEV_MODE", False):
            # Keep the local A1 setup self-contained without changing the
            # fiscal worker's queueing semantics or running a SEFAZ request in
            # the web process.
            process_certificate_upload(upload_id)
            return
        from apps.certificates.tasks import process_staged_certificate_upload

        process_staged_certificate_upload.delay(upload_id)

    return dispatch


def _mark_upload_failed(upload_id: int, *, now: datetime, message: str) -> None:
    with transaction.atomic():
        upload = (
            CertificateUpload.objects.select_for_update().filter(pk=upload_id).first()
        )
        if upload is None or upload.status in {
            CertificateUpload.Status.COMPLETED,
            CertificateUpload.Status.FAILED,
            CertificateUpload.Status.EXPIRED,
        }:
            return
        _discard_upload(
            upload,
            status=CertificateUpload.Status.FAILED,
            now=now,
            message=message,
        )


def _discard_upload(
    upload: CertificateUpload,
    *,
    status: str,
    now: datetime,
    message: str | None = None,
) -> None:
    upload.status = status
    upload.encrypted_payload = None
    upload.encrypted_password = None
    upload.error_message = message or (
        "O envio expirou antes de ser processado. Envie o certificado novamente."
        if status == CertificateUpload.Status.EXPIRED
        else "Não foi possível validar o certificado ou a senha informada."
    )
    upload.processed_at = now
    upload.save(
        update_fields=(
            "status",
            "encrypted_payload",
            "encrypted_password",
            "error_message",
            "processed_at",
        )
    )
    AuditLog.objects.create(
        actor=upload.uploaded_by,
        action=(
            "certificates.upload_expired"
            if status == CertificateUpload.Status.EXPIRED
            else "certificates.upload_failed"
        ),
        target=f"certificates.upload:{upload.pk}",
        payload={"company_id": upload.company_id},
    )
