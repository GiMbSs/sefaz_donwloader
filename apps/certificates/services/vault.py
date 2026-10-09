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
from django.contrib.auth.hashers import check_password, make_password
from django.db import transaction
from django.utils import timezone

from apps.certificates.models import DigitalCertificate
from apps.organizations.storage import company_storage_directory

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
            raise CertificateVaultError(
                "Certificate vault key is unavailable."
            ) from error
        try:
            key = base64.urlsafe_b64decode(encoded)
        except (ValueError, binascii.Error) as error:
            raise CertificateVaultError(
                "Certificate vault key has an invalid encoding."
            ) from error
        if len(key) != 32:
            raise CertificateVaultError(
                "Certificate vault key must decode to 32 bytes."
            )
        return key

    @staticmethod
    def _associated_data(storage_id: object, purpose: str = "pfx") -> bytes:
        return f"sefaz-downloader:certificate:{storage_id}:{purpose}".encode("ascii")

    @staticmethod
    def _legacy_associated_data(storage_id: object) -> bytes:
        return f"sefaz-downloader:certificate:{storage_id}".encode("ascii")

    def seal(
        self,
        plaintext: bytes,
        storage_id: object,
        *,
        purpose: str = "pfx",
    ) -> bytes:
        nonce = os.urandom(self._NONCE_SIZE)
        ciphertext = AESGCM(self._key()).encrypt(
            nonce,
            plaintext,
            self._associated_data(storage_id, purpose),
        )
        return self._MAGIC + nonce + ciphertext

    def unseal(
        self,
        payload: bytes,
        storage_id: object,
        *,
        purpose: str = "pfx",
    ) -> bytes:
        if not payload.startswith(self._MAGIC) or len(payload) <= (
            len(self._MAGIC) + self._NONCE_SIZE
        ):
            raise CertificateVaultError(
                "Certificate vault payload has an invalid format."
            )
        nonce_start = len(self._MAGIC)
        nonce_end = nonce_start + self._NONCE_SIZE
        try:
            return AESGCM(self._key()).decrypt(
                payload[nonce_start:nonce_end],
                payload[nonce_end:],
                self._associated_data(storage_id, purpose),
            )
        except Exception as error:  # cryptography has few public AEAD error types
            raise CertificateVaultError(
                "Certificate vault payload cannot be decrypted."
            ) from error

    def unseal_legacy(self, payload: bytes, storage_id: object) -> bytes:
        """Read version-1 vault content while migrating it out of the database."""
        if not payload.startswith(self._MAGIC) or len(payload) <= (
            len(self._MAGIC) + self._NONCE_SIZE
        ):
            raise CertificateVaultError("Legacy certificate vault payload is invalid.")
        nonce_start = len(self._MAGIC)
        nonce_end = nonce_start + self._NONCE_SIZE
        try:
            return AESGCM(self._key()).decrypt(
                payload[nonce_start:nonce_end],
                payload[nonce_end:],
                self._legacy_associated_data(storage_id),
            )
        except Exception as error:
            raise CertificateVaultError(
                "Legacy certificate vault payload cannot be decrypted."
            ) from error

    def _client_directory(
        self,
        *,
        company: ClientCompany | None = None,
        company_id: int | None = None,
    ) -> Path:
        """Return a private certificate folder.

        ``company_id`` remains supported only to read/migrate the legacy layout
        referenced by the historical credential migration.  New registrations
        always provide the company object and use the tenant-scoped
        ``empresa_<cnpj>/certificado`` layout.
        """
        if company is not None:
            return self.root / company_storage_directory(company) / "certificado"
        if company_id is None:
            raise CertificateVaultError("A company is required for certificate storage.")
        return self.root / "clientes" / str(company_id) / "certificados"

    def _path_for(
        self,
        *,
        company: ClientCompany | None = None,
        company_id: int | None = None,
        storage_id: object,
        purpose: str,
    ) -> Path:
        suffix = "pfx.enc" if purpose == "pfx" else "password.enc"
        return (
            self._client_directory(company=company, company_id=company_id)
            / f"{storage_id}.{suffix}"
        )

    def store_certificate(
        self,
        *,
        company: ClientCompany | None = None,
        company_id: int | None = None,
        storage_id: object,
        payload: bytes,
    ) -> str:
        return self._store(
            company=company,
            company_id=company_id,
            storage_id=storage_id,
            payload=payload,
            purpose="pfx",
        )

    def store_password(
        self,
        *,
        company: ClientCompany | None = None,
        company_id: int | None = None,
        storage_id: object,
        password: str,
    ) -> str:
        return self._store(
            company=company,
            company_id=company_id,
            storage_id=storage_id,
            payload=password.encode("utf-8"),
            purpose="password",
        )

    def _store(
        self,
        *,
        company: ClientCompany | None,
        company_id: int | None,
        storage_id: object,
        payload: bytes,
        purpose: str,
    ) -> str:
        target = self._path_for(
            company=company,
            company_id=company_id,
            storage_id=storage_id,
            purpose=purpose,
        )
        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        encrypted = self.seal(payload, storage_id, purpose=purpose)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=".upload-",
            dir=target.parent,
        )
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
        encrypted = self._read_path(
            certificate.encrypted_path,
            message="Encrypted certificate material is unavailable.",
        )
        return self.unseal(encrypted, certificate.storage_id, purpose="pfx")

    def unseal_password(self, certificate: DigitalCertificate) -> str:
        encrypted = self._read_path(
            certificate.encrypted_password_path,
            message="Encrypted certificate password is unavailable.",
        )
        try:
            password = self.unseal(
                encrypted,
                certificate.storage_id,
                purpose="password",
            ).decode("utf-8")
        except UnicodeDecodeError as error:
            raise CertificateVaultError(
                "Encrypted certificate password is invalid."
            ) from error
        try:
            matches = check_password(password, certificate.password_hash)
        except ValueError as error:
            raise CertificateVaultError(
                "Certificate password verification is unavailable."
            ) from error
        if not matches:
            raise CertificateVaultError("Certificate password verification failed.")
        return password

    def load_legacy(self, encrypted_path: str, storage_id: object) -> bytes:
        encrypted = self._read_path(
            encrypted_path,
            message="Legacy encrypted certificate material is unavailable.",
        )
        return self.unseal_legacy(encrypted, storage_id)

    def unseal_legacy_password(self, sealed_password: str, storage_id: object) -> str:
        try:
            payload = base64.urlsafe_b64decode(sealed_password.encode("ascii"))
            return self.unseal_legacy(payload, storage_id).decode("utf-8")
        except (UnicodeDecodeError, ValueError, binascii.Error) as error:
            raise CertificateVaultError(
                "Legacy encrypted certificate password is unavailable."
            ) from error

    def remove(self, certificate: DigitalCertificate) -> None:
        self._remove_path(certificate.encrypted_path)
        self._remove_path(certificate.encrypted_password_path)

    def remove_legacy(self, encrypted_path: str) -> None:
        self._remove_path(encrypted_path)

    def _read_path(self, relative_path: str, *, message: str) -> bytes:
        target = self._resolve_path(relative_path)
        try:
            return target.read_bytes()
        except OSError as error:
            raise CertificateVaultError(message) from error

    def _remove_path(self, relative_path: str) -> None:
        target = self._resolve_path(relative_path)
        try:
            target.unlink()
        except FileNotFoundError:
            return
        except OSError as error:
            raise CertificateVaultError(
                "Encrypted certificate material cannot be removed."
            ) from error

    def _resolve_path(self, relative_path: str) -> Path:
        target = (self.root / Path(relative_path)).resolve()
        if self.root.resolve() not in target.parents:
            raise CertificateVaultError("Certificate path escaped the private vault.")
        return target


def inspect_pkcs12(payload: bytes, password: str) -> CertificateMetadata:
    """Parse a PFX in memory without persisting plaintext on disk."""
    try:
        private_key, certificate, _additional = pkcs12.load_key_and_certificates(
            payload,
            password.encode("utf-8"),
        )
    except (TypeError, ValueError) as error:
        raise CertificateValidationError(
            "The PFX file or its password is invalid."
        ) from error
    if private_key is None or certificate is None:
        raise CertificateValidationError(
            "The PFX must contain a private key and certificate."
        )

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
        raise CertificateValidationError(
            "The certificate file exceeds the allowed size."
        )
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
        encrypted_password_path="pending",
        password_hash="pending",
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
        certificate.encrypted_path = vault.store_certificate(
            company=company,
            storage_id=certificate.storage_id,
            payload=payload,
        )
        certificate.encrypted_password_path = vault.store_password(
            company=company,
            storage_id=certificate.storage_id,
            password=password,
        )
        certificate.password_hash = make_password(password)
        with transaction.atomic():
            active_certificates = DigitalCertificate.objects.select_for_update().filter(
                company=company,
                status=DigitalCertificate.Status.ACTIVE,
            )
            active_certificates.update(
                status=DigitalCertificate.Status.REPLACED,
                replaced_at=now,
            )
            certificate.full_clean(
                exclude={
                    "encrypted_path",
                    "encrypted_password_path",
                    "password_hash",
                }
            )
            certificate.save()
    except Exception:
        try:
            vault.remove(certificate)
        except CertificateVaultError:
            pass
        raise
    return certificate
