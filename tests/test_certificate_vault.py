import base64
from types import SimpleNamespace
from typing import cast

from django.contrib.auth.hashers import make_password

from apps.certificates.models import DigitalCertificate
from apps.certificates.services.vault import CertificateVault


def test_vault_round_trip_binds_ciphertext_to_storage_identifier(tmp_path):
    key_file = tmp_path / "vault.key"
    key_file.write_bytes(base64.urlsafe_b64encode(b"a" * 32))
    vault = CertificateVault(root=tmp_path / "certificates", key_file=key_file)

    encrypted = vault.seal(b"certificate material", "storage-one")

    assert vault.unseal(encrypted, "storage-one") == b"certificate material"


def test_vault_stores_each_clients_certificate_and_secret_in_private_files(tmp_path):
    key_file = tmp_path / "vault.key"
    key_file.write_bytes(base64.urlsafe_b64encode(b"b" * 32))
    vault = CertificateVault(root=tmp_path / "certificates", key_file=key_file)

    certificate_path = vault.store_certificate(
        company_id=42,
        storage_id="certificate-one",
        payload=b"certificate material",
    )
    password_path = vault.store_password(
        company_id=42,
        storage_id="certificate-one",
        password="senha-secreta",
    )
    certificate = cast(
        DigitalCertificate,
        SimpleNamespace(
            encrypted_path=certificate_path,
            encrypted_password_path=password_path,
            password_hash=make_password("senha-secreta"),
            storage_id="certificate-one",
        ),
    )

    assert certificate_path.startswith("clientes/42/certificados/")
    assert password_path.startswith("clientes/42/certificados/")
    assert vault.load(certificate) == b"certificate material"
    assert vault.unseal_password(certificate) == "senha-secreta"
