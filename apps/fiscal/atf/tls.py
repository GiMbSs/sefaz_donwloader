"""Load the enterprise A1 into TLS without persisting an unencrypted key."""

import csv
import hashlib
import io
import os
import re
import ssl
import subprocess
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.serialization import pkcs12
from django.conf import settings
from django.utils import timezone
from requests.adapters import HTTPAdapter

from apps.certificates.models import DigitalCertificate
from apps.certificates.services.identity import certificate_cnpj
from apps.certificates.services.vault import CertificateVault

from .errors import AtfAuthenticationError, AtfIdentityMismatch


class MutualTlsAdapter(HTTPAdapter):
    def __init__(self, context: Any) -> None:
        self.context = context
        super().__init__()

    def init_poolmanager(
        self, connections: Any, maxsize: Any, block: Any = False, **kwargs: Any
    ) -> Any:
        super().init_poolmanager(
            connections, maxsize, block, ssl_context=self.context, **kwargs
        )

    def proxy_manager_for(self, proxy: Any, **kwargs: Any) -> Any:
        return super().proxy_manager_for(proxy, ssl_context=self.context, **kwargs)


def _protect_windows_directory(path: Path) -> None:
    try:
        identity = subprocess.run(
            ["whoami", "/user", "/fo", "csv", "/nh"],
            capture_output=True,
            text=True,
            check=True,
        )
        rows = list(csv.reader(io.StringIO(identity.stdout)))
        sid = rows[-1][-1].strip()
        if not re.fullmatch(r"S-1-[0-9-]+", sid):
            raise ValueError("Invalid account identity")
        subprocess.run(
            ["icacls", str(path), "/inheritance:r", "/grant:r", f"*{sid}:(OI)(CI)F"],
            capture_output=True,
            check=True,
        )
    except (OSError, ValueError, IndexError, subprocess.CalledProcessError):
        raise AtfAuthenticationError("atf_private_tls_directory_unavailable") from None


@dataclass(frozen=True, repr=False)
class VerifiedA1:
    pfx: bytes
    passphrase: str
    company_cnpj: str


def load_verified_a1(certificate_id: int) -> VerifiedA1:
    stored = DigitalCertificate.objects.select_related("company").get(
        pk=certificate_id, status=DigitalCertificate.Status.ACTIVE
    )
    now = timezone.now()
    if not stored.not_valid_before <= now <= stored.not_valid_after:
        raise AtfAuthenticationError("atf_certificate_expired")
    vault = CertificateVault()
    password = vault.unseal_password(stored)
    payload = vault.load(stored)
    key, certificate, chain = pkcs12.load_key_and_certificates(
        payload, password.encode("utf-8")
    )
    if key is None or certificate is None:
        raise AtfAuthenticationError()
    if (
        certificate_cnpj(certificate) != stored.company.tax_identifier
        or certificate.fingerprint(hashes.SHA256()).hex()
        != stored.certificate_fingerprint_sha256
        or hashlib.sha256(payload).hexdigest() != stored.content_sha256
    ):
        raise AtfIdentityMismatch()
    if not certificate.not_valid_before_utc <= now <= certificate.not_valid_after_utc:
        raise AtfAuthenticationError("atf_certificate_expired")
    return VerifiedA1(payload, password, stored.company.tax_identifier)


@contextmanager
def client_tls_context(certificate_id: int) -> Any:
    material = load_verified_a1(certificate_id)
    password = material.passphrase
    key, certificate, chain = pkcs12.load_key_and_certificates(
        material.pfx, password.encode("utf-8")
    )
    del material
    if key is None or certificate is None:
        raise AtfAuthenticationError()
    ca_bundle = getattr(settings, "ATF_TLS_CA_BUNDLE", "") or requests.certs.where()
    context = ssl.create_default_context(cafile=ca_bundle)
    public = certificate.public_bytes(serialization.Encoding.PEM)
    public += b"".join(
        item.public_bytes(serialization.Encoding.PEM) for item in chain or []
    )
    if hasattr(os, "memfd_create"):
        descriptor = os.memfd_create("atf-client", os.MFD_CLOEXEC)
        try:
            private = key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            )
            with os.fdopen(os.dup(descriptor), "wb") as stream:
                stream.write(public + private)
            context.load_cert_chain(f"/proc/self/fd/{descriptor}")
        finally:
            os.close(descriptor)
        del private, key, password
        yield context
    elif os.name == "nt":
        root = Path.home() / ".sefaz_downloader" / "private-tls"
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="atf-", dir=root) as folder:
            directory = Path(folder)
            _protect_windows_directory(directory)
            passphrase = os.urandom(32)
            private = key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.BestAvailableEncryption(passphrase),
            )
            pem_file = directory / "client.pem"
            pem_file.write_bytes(public + private)
            context.load_cert_chain(str(pem_file), password=passphrase)
            del private, key, password, passphrase
            yield context
    else:
        raise AtfAuthenticationError("atf_private_tls_backend_unavailable")
