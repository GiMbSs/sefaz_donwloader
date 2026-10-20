import base64
from pathlib import Path

import pytest

from apps.certificates.services.vault import CertificateVault, register_certificate
from apps.organizations.models import AccountingOffice, ClientCompany
from tests.certificate_helpers import make_a1


@pytest.fixture
def binding(tmp_path, settings, db):
    settings.CERTIFICATE_VAULT_ROOT = tmp_path / "vault"
    settings.CERTIFICATE_ENCRYPTION_KEY_FILE = tmp_path / "key"
    settings.CERTIFICATE_ENCRYPTION_KEY_FILE.write_bytes(
        base64.urlsafe_b64encode(b"k" * 32)
    )
    office = AccountingOffice.objects.create(
        legal_name="Office", tax_identifier="00000000000191"
    )
    company = ClientCompany.objects.create(
        office=office, legal_name="Company", tax_identifier="00000000000191"
    )
    certificate = register_certificate(
        company=company,
        filename="synthetic.pfx",
        payload=make_a1(),
        password="test-password",
        uploaded_by=None,
    )
    return certificate, CertificateVault()


def test_vault_accepts_windows_relative_separators(binding):
    certificate, vault = binding
    certificate.encrypted_path = certificate.encrypted_path.replace("/", "\\")
    assert vault.load(certificate)


def test_reconciliation_reports_matched_binding_without_mutating(binding):
    from apps.certificates.services.reconciliation import inspect_vault_binding

    certificate, _ = binding
    before = certificate.storage_id
    result = inspect_vault_binding(certificate.pk)
    assert result.state == "matched"
    certificate.refresh_from_db()
    assert certificate.storage_id == before


def test_reconciliation_never_accepts_a_different_certificate(binding):
    from apps.certificates.services.reconciliation import inspect_vault_binding

    certificate, vault = binding
    path = Path(certificate.encrypted_path)
    full = vault.root / path
    full.write_bytes(vault.seal(make_a1(), certificate.storage_id, purpose="pfx"))
    assert inspect_vault_binding(certificate.pk).state == "divergent"


def test_vault_rejects_windows_absolute_and_traversal(binding):
    from apps.certificates.services.vault import CertificateVaultError

    certificate, vault = binding
    for bad in ["C:\\secret.pfx", "..\\secret.pfx", "/etc/passwd"]:
        certificate.encrypted_path = bad
        with pytest.raises(CertificateVaultError):
            vault.load(certificate)


def test_operator_cannot_rebind_the_vault(binding):
    from django.contrib.auth import get_user_model
    from django.core.exceptions import PermissionDenied

    from apps.certificates.services.reconciliation import apply_verified_binding

    certificate, _ = binding
    operator = get_user_model().objects.create_user(email="operator@example.test")
    with pytest.raises(PermissionDenied):
        apply_verified_binding(
            certificate.pk, certificate.storage_id, actor_id=operator.pk
        )
