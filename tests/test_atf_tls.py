import ssl

import pytest


def test_verified_a1_for_browser_keeps_credentials_in_memory(binding):
    from apps.fiscal.atf.tls import load_verified_a1

    stored, vault = binding
    material = load_verified_a1(stored.pk)
    assert material.pfx == vault.load(stored)
    assert material.passphrase == vault.unseal_password(stored)
    assert material.company_cnpj == stored.company.tax_identifier
    assert material.passphrase not in repr(material)


def test_browser_a1_rejects_an_unrelated_company(binding):
    from apps.fiscal.atf.errors import AtfIdentityMismatch
    from apps.fiscal.atf.tls import load_verified_a1

    certificate, _ = binding
    certificate.company.tax_identifier = "11111111000111"
    certificate.company.save(update_fields=["tax_identifier"])
    with pytest.raises(AtfIdentityMismatch):
        load_verified_a1(certificate.pk)


def test_tls_context_loads_a1_in_memory_and_keeps_server_verification(binding):
    from apps.fiscal.atf.tls import client_tls_context

    certificate, _ = binding
    with client_tls_context(certificate.pk) as context:
        assert context.verify_mode == ssl.CERT_REQUIRED
        assert context.check_hostname


def test_tls_context_rejects_unrelated_company_certificate(binding):
    from apps.fiscal.atf.errors import AtfIdentityMismatch
    from apps.fiscal.atf.tls import client_tls_context

    certificate, _ = binding
    certificate.company.tax_identifier = "11111111000111"
    certificate.company.save(update_fields=["tax_identifier"])
    with pytest.raises(AtfIdentityMismatch), client_tls_context(certificate.pk):
        pytest.fail("Unrelated A1 was accepted")


def test_tls_rejects_changed_certificate_even_for_the_same_company(binding):
    from apps.fiscal.atf.errors import AtfIdentityMismatch
    from apps.fiscal.atf.tls import client_tls_context
    from tests.certificate_helpers import make_a1

    certificate, vault = binding
    path = vault.root / certificate.encrypted_path
    path.write_bytes(vault.seal(make_a1(), certificate.storage_id, purpose="pfx"))
    with pytest.raises(AtfIdentityMismatch), client_tls_context(certificate.pk):
        pytest.fail("Changed certificate was accepted without reconciliation")
