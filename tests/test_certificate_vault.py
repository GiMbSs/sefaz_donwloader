import base64

from apps.certificates.services.vault import CertificateVault


def test_vault_round_trip_binds_ciphertext_to_storage_identifier(tmp_path):
    key_file = tmp_path / "vault.key"
    key_file.write_bytes(base64.urlsafe_b64encode(b"a" * 32))
    vault = CertificateVault(root=tmp_path / "certificates", key_file=key_file)

    encrypted = vault.seal(b"certificate material", "storage-one")

    assert vault.unseal(encrypted, "storage-one") == b"certificate material"

