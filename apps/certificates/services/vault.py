"""Private encrypted storage for A1/PFX material.

The vault is intentionally independent from Django's public media storage.
Only worker-side application services are allowed to call it.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import os
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.serialization import pkcs12
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.certificates.models import DigitalCertificate

if TYPE_CHECKING:
    from apps.accounts.models import User
    from apps.organizations.models import ClientCompany


class CertificateVaultError(Exception):
    """Raised when protected certificate material cannot be used safely."""


class CertificateValidationError(CertificateVaultError):
    """Raised when the uploaded content is not a usable A1/PFX certificate."""


@dataclass(frozen=True)
class CertificateMetadata:
    serial_number: str
    subject: str
    issuer: str
    fingerprint_sha256: str
    not_valid_before: datetime
    not_valid_after: datetime


class CertificateVault:
    _MAGIC = b"SFD1"
    _NONCE_SIZE = 12

    def __init__(self, root: Path | None = None, key_file: Path | None = None) -> None:
        self.root = root or settings.CERTIFICATE_VAULT_ROOT
        self.key_file = key_file or settings.CERTIFICATE_ENCRYPTION_KEY_FILE

    def _key(self) -> bytes:
        try:
            encoded = self.key_file.read_bytes().strip()
        except OSError as error:
            raise CertificateVaultError("Certificate vault key is unavailable.") from error
        try:
            key = base64.urlsafe_b64decode(encoded)
        except (ValueError, binascii.Error) as error:
            raise CertificateVaultError("Certificate vault key has an invalid encoding.") from error
        if len(key) != 32:
            raise CertificateVaultError("Certificate vault key must decode to 32 bytes.")
        return key

    @staticmethod
    def _associated_data(storage_id: object) -> bytes:
        return f"sefaz-downloader:certificate:{storage_id}".encode("ascii")

    def seal(self, plaintext: bytes, storage_id: object) -> bytes:
        nonce = os.urandom(self._NONCE_SIZE)
        ciphertext = AESGCM(self._key()).encrypt(
            nonce,
            plaintext,
            self._associated_data(storage_id),
        )
        return self._MAGIC + nonce + ciphertext

    def unseal(self, payload: bytes, storage_id: object) -> bytes:
        if not payload.startswith(self._MAGIC) or len(payload) <= len(self._MAGIC) + self._NONCE_SIZE:
            raise CertificateVaultError("Certificate vault payload has an invalid format.")
        nonce_start = len(self._MAGIC)
        nonce_end = nonce_start + self._NONCE_SIZE
        try:
            return AESGCM(self._key()).decrypt(
                payload[nonce_start:nonce_end],
                payload[nonce_end:],
                self._associated_data(storage_id),
            )
        except Exception as error:  # cryptography deliberately has few public AEAD errors
            raise CertificateVaultError("Certificate vault payload cannot be decrypted.") from error

    def _path_for(self, storage_id: object) -> Path:
        return self.root / "pfx" / f"{storage_id}.bin"

    def store(self, storage_id: object, payload: bytes) -> str:
        target = self._path_for(storage_id)
        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        encrypted = self.seal(payload, storage_id)
        descriptor, temporary_name = tempfile.mkstemp(prefix=".upload-", dir=target.parent)
        try:
            with os.fdopen(descriptor, "wb") as temporary:
                os.fchmod(temporary.fileno(), 0o600)
                temporary.write(encrypted)
                temporary.flush()
                os.fsync(temporary.fileno())
            os.replace(temporary_name, target)
            os.chmod(target, 0o600)
        except OSError:
            try:
                os.unlink(temporary_name)
            except FileNotFoundError:
                pass
            raise
        return str(target.relative_to(self.root))

    def load(self, certificate: DigitalCertificate) -> bytes:
        relative_path = Path(certificate.encrypted_path)
        target = (self.root / relative_path).resolve()
        if self.root.resolve() not in target.parents:
            raise CertificateVaultError("Certificate path escaped the private vault.")
        try:
            encrypted = target.read_bytes()
        except OSError as error:
            raise CertificateVaultError("Encrypted certificate material is unavailable.") from error
        return self.unseal(encrypted, certificate.storage_id)

    def remove(self, storage_id: object) -> None:
        try:
            self._path_for(storage_id).unlink()
        except FileNotFoundError:
            return
        except OSError as error:
            raise CertificateVaultError("Encrypted certificate material cannot be removed.") from error

    def seal_password(self, password: str, storage_id: object) -> str:
        return base64.urlsafe_b64encode(self.seal(password.encode("utf-8"), storage_id)).decode("ascii")

    def unseal_password(self, certificate: DigitalCertificate) -> str:
        try:
            payload = base64.urlsafe_b64decode(certificate.sealed_password.encode("ascii"))
            return self.unseal(payload, certificate.storage_id).decode("utf-8")
        except (UnicodeDecodeError, ValueError, binascii.Error) as error:
            raise CertificateVaultError("Encrypted certificate password is unavailable.") from error


def inspect_pkcs12(payload: bytes, password: str) -> CertificateMetadata:
    """Parse a PFX in memory without persisting plaintext on disk."""
    try:
        private_key, certificate, _additional = pkcs12.load_key_and_certificates(
            payload,
            password.encode("utf-8"),
        )
    except (TypeError, ValueError) as error:
        raise CertificateValidationError("The PFX file or its password is invalid.") from error
    if private_key is None or certificate is None:
        raise CertificateValidationError("The PFX must contain a private key and certificate.")

    return CertificateMetadata(
        serial_number=format(certificate.serial_number, "X"),
        subject=certificate.subject.rfc4514_string(),
        issuer=certificate.issuer.rfc4514_string(),
        fingerprint_sha256=certificate.fingerprint(hashes.SHA256()).hex(),
        not_valid_before=_certificate_datetime(certificate, "not_valid_before"),
        not_valid_after=_certificate_datetime(certificate, "not_valid_after"),
    )


def _certificate_datetime(certificate: x509.Certificate, attribute: str) -> datetime:
    utc_attribute = f"{attribute}_utc"
    value = getattr(certificate, utc_attribute, None)
    if value is None:
        value = getattr(certificate, attribute).replace(tzinfo=UTC)
    return value.astimezone(UTC)


def register_certificate(
    *,
    company: ClientCompany,
    filename: str,
    payload: bytes,
    password: str,
    uploaded_by: User | None,
    vault: CertificateVault | None = None,
) -> DigitalCertificate:
    """Inspect, encrypt, and activate a replacement A1 certificate atomically."""
    if not payload:
        raise CertificateValidationError("The certificate file is empty.")
    if len(payload) > settings.CERTIFICATE_MAX_UPLOAD_BYTES:
        raise CertificateValidationError("The certificate file exceeds the allowed size.")
    if not password:
        raise CertificateValidationError("The certificate password is required.")

    metadata = inspect_pkcs12(payload, password)
    now = timezone.now()
    if metadata.not_valid_after <= now:
        raise CertificateValidationError("The certificate is expired.")

    vault = vault or CertificateVault()
    certificate = DigitalCertificate(
        company=company,
        encrypted_path="pending",
        sealed_password="pending",
        filename=Path(filename).name[:255],
        content_sha256=hashlib.sha256(payload).hexdigest(),
        certificate_fingerprint_sha256=metadata.fingerprint_sha256,
        serial_number=metadata.serial_number,
        subject=metadata.subject,
        issuer=metadata.issuer,
        not_valid_before=metadata.not_valid_before,
        not_valid_after=metadata.not_valid_after,
        uploaded_by=uploaded_by,
    )
    try:
        certificate.encrypted_path = vault.store(certificate.storage_id, payload)
        certificate.sealed_password = vault.seal_password(password, certificate.storage_id)
        with transaction.atomic():
            active_certificates = DigitalCertificate.objects.select_for_update().filter(
                company=company,
                status=DigitalCertificate.Status.ACTIVE,
            )
            active_certificates.update(
                status=DigitalCertificate.Status.REPLACED,
                replaced_at=now,
            )
            certificate.full_clean(exclude={"encrypted_path", "sealed_password"})
            certificate.save()
    except Exception:
        vault.remove(certificate.storage_id)
        raise
    return certificate
