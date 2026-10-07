"""Hybrid encryption for short-lived certificate uploads sent to the worker."""

from __future__ import annotations

import base64
import binascii
import os
from pathlib import Path
from uuid import UUID

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import x25519
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from django.conf import settings


class CertificateUploadEnvelopeError(Exception):
    """The encrypted web-to-worker envelope cannot be used safely."""


class CertificateUploadEnvelope:
    """Encrypt with the worker's public X25519 key; decrypt only in the worker."""

    _MAGIC = b"SFU1"
    _PUBLIC_KEY_SIZE = 32
    _NONCE_SIZE = 12

    def __init__(
        self,
        *,
        public_key_file: Path | None = None,
        private_key_file: Path | None = None,
    ) -> None:
        self.public_key_file = (
            public_key_file or settings.CERTIFICATE_UPLOAD_PUBLIC_KEY_FILE
        )
        self.private_key_file = (
            private_key_file or settings.CERTIFICATE_UPLOAD_PRIVATE_KEY_FILE
        )

    def encrypt(self, plaintext: bytes, *, request_id: UUID, purpose: str) -> bytes:
        if not plaintext:
            raise CertificateUploadEnvelopeError(
                "Certificate upload data cannot be empty."
            )
        try:
            recipient = x25519.X25519PublicKey.from_public_bytes(
                self._read_key(self.public_key_file)
            )
        except ValueError as error:
            raise CertificateUploadEnvelopeError(
                "Certificate upload public key is invalid."
            ) from error
        ephemeral_private = x25519.X25519PrivateKey.generate()
        ephemeral_public = ephemeral_private.public_key().public_bytes(
            serialization.Encoding.Raw,
            serialization.PublicFormat.Raw,
        )
        key = self._derive_key(
            ephemeral_private.exchange(recipient),
            request_id=request_id,
            purpose=purpose,
        )
        nonce = os.urandom(self._NONCE_SIZE)
        ciphertext = AESGCM(key).encrypt(
            nonce,
            plaintext,
            self._associated_data(request_id, purpose),
        )
        return self._MAGIC + ephemeral_public + nonce + ciphertext

    def decrypt(self, envelope: bytes, *, request_id: UUID, purpose: str) -> bytes:
        minimum_size = len(self._MAGIC) + self._PUBLIC_KEY_SIZE + self._NONCE_SIZE + 16
        if not envelope.startswith(self._MAGIC) or len(envelope) < minimum_size:
            raise CertificateUploadEnvelopeError(
                "Certificate upload has an invalid envelope format."
            )
        offset = len(self._MAGIC)
        try:
            peer_public = x25519.X25519PublicKey.from_public_bytes(
                envelope[offset : offset + self._PUBLIC_KEY_SIZE]
            )
        except ValueError as error:
            raise CertificateUploadEnvelopeError(
                "Certificate upload envelope contains an invalid public key."
            ) from error
        offset += self._PUBLIC_KEY_SIZE
        nonce = envelope[offset : offset + self._NONCE_SIZE]
        ciphertext = envelope[offset + self._NONCE_SIZE :]
        try:
            private_key = x25519.X25519PrivateKey.from_private_bytes(
                self._read_key(self.private_key_file)
            )
        except ValueError as error:
            raise CertificateUploadEnvelopeError(
                "Certificate upload private key is invalid."
            ) from error
        key = self._derive_key(
            private_key.exchange(peer_public),
            request_id=request_id,
            purpose=purpose,
        )
        try:
            return AESGCM(key).decrypt(
                nonce,
                ciphertext,
                self._associated_data(request_id, purpose),
            )
        except InvalidTag as error:
            raise CertificateUploadEnvelopeError(
                "Certificate upload envelope authentication failed."
            ) from error

    @staticmethod
    def _associated_data(request_id: UUID, purpose: str) -> bytes:
        return (
            f"sefaz-downloader:certificate-upload:{request_id}:{purpose}"
        ).encode("ascii")

    @staticmethod
    def _derive_key(shared_secret: bytes, *, request_id: UUID, purpose: str) -> bytes:
        return HKDF(
            algorithm=hashes.SHA256(),
            length=32,
            salt=request_id.bytes,
            info=f"sefaz-downloader:certificate-upload:{purpose}".encode("ascii"),
        ).derive(shared_secret)

    @staticmethod
    def _read_key(path: Path) -> bytes:
        try:
            raw_key = base64.urlsafe_b64decode(path.read_bytes().strip())
        except (OSError, ValueError, binascii.Error) as error:
            raise CertificateUploadEnvelopeError(
                "Certificate upload key is unavailable or invalid."
            ) from error
        if len(raw_key) != CertificateUploadEnvelope._PUBLIC_KEY_SIZE:
            raise CertificateUploadEnvelopeError(
                "Certificate upload key must decode to 32 bytes."
            )
        return raw_key


def generate_upload_keypair(
    *,
    private_key_file: Path | None = None,
    public_key_file: Path | None = None,
    if_missing: bool = False,
) -> bool:
    """Generate an X25519 keypair without ever overwriting deployment keys."""
    private_path = private_key_file or settings.CERTIFICATE_UPLOAD_PRIVATE_KEY_FILE
    public_path = public_key_file or settings.CERTIFICATE_UPLOAD_PUBLIC_KEY_FILE
    if private_path.exists() or public_path.exists():
        if if_missing and private_path.exists() and public_path.exists():
            return False
        raise CertificateUploadEnvelopeError(
            "Certificate upload keypair is incomplete or already exists."
        )

    private_key = x25519.X25519PrivateKey.generate()
    private_material = private_key.private_bytes(
        serialization.Encoding.Raw,
        serialization.PrivateFormat.Raw,
        serialization.NoEncryption(),
    )
    public_material = private_key.public_key().public_bytes(
        serialization.Encoding.Raw,
        serialization.PublicFormat.Raw,
    )
    try:
        _write_key(private_path, private_material, mode=0o600)
        _write_key(public_path, public_material, mode=0o644)
    except Exception:
        try:
            private_path.unlink()
        except FileNotFoundError:
            pass
        raise
    return True


def _write_key(path: Path, key: bytes, *, mode: int) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    with os.fdopen(descriptor, "wb") as key_file:
        key_file.write(base64.urlsafe_b64encode(key))
        key_file.write(b"\n")
