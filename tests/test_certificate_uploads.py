import base64
from datetime import UTC, datetime, timedelta

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509.oid import NameOID
from django.utils import timezone

from apps.accounts.models import User
from apps.certificates.models import CertificateUpload
from apps.certificates.services.upload_envelope import (
    CertificateUploadEnvelope,
    generate_upload_keypair,
)
from apps.certificates.services.uploads import (
    expire_staged_certificate_uploads,
    process_certificate_upload,
    stage_certificate_upload,
)
from apps.certificates.services.vault import CertificateVault
from apps.operations.models import AuditLog
from apps.organizations.models import AccountingOffice, ClientCompany


def _company_and_user() -> tuple[ClientCompany, User]:
    user = User.objects.create_user(email="admin@example.test", password="senha-segura")
    office = AccountingOffice.objects.create(
        legal_name="Contabilidade Exemplo Ltda.",
        tax_identifier="00000000000191",
    )
    company = ClientCompany.objects.create(
        office=office,
        legal_name="Cliente Exemplo Ltda.",
        tax_identifier="00000000000191",
    )
    return company, user


def _valid_pkcs12(password: str) -> bytes:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Empresa Exemplo")])
    now = datetime.now(UTC)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(private_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(days=30))
        .sign(private_key, hashes.SHA256())
    )
    return pkcs12.serialize_key_and_certificates(
        name=b"empresa-exemplo",
        key=private_key,
        cert=certificate,
        cas=None,
        encryption_algorithm=serialization.BestAvailableEncryption(password.encode()),
    )


@pytest.mark.django_db
def test_staged_upload_only_stores_encrypted_material_and_is_idempotent(tmp_path):
    company, user = _company_and_user()
    private_key = tmp_path / "private.key"
    public_key = tmp_path / "public.key"
    generate_upload_keypair(private_key_file=private_key, public_key_file=public_key)
    web_envelope = CertificateUploadEnvelope(public_key_file=public_key)
    worker_envelope = CertificateUploadEnvelope(
        public_key_file=public_key,
        private_key_file=private_key,
    )

    first = stage_certificate_upload(
        company_id=company.pk,
        filename="empresa.pfx",
        payload=b"test-pfx-content",
        password="senha-secreta",
        uploaded_by=user,
        envelope=web_envelope,
        dispatch=False,
    )
    repeated = stage_certificate_upload(
        company_id=company.pk,
        filename="empresa.pfx",
        payload=b"other-content",
        password="outra-senha",
        uploaded_by=user,
        envelope=web_envelope,
        dispatch=False,
    )

    first.upload.refresh_from_db()
    assert first.created is True
    assert repeated.created is False
    assert repeated.upload.pk == first.upload.pk
    assert b"test-pfx-content" not in bytes(first.upload.encrypted_payload)
    assert b"senha-secreta" not in bytes(first.upload.encrypted_password)
    assert worker_envelope.decrypt(
        bytes(first.upload.encrypted_payload),
        request_id=first.upload.request_id,
        purpose="pfx",
    ) == b"test-pfx-content"
    assert AuditLog.objects.filter(action="certificates.upload_staged").count() == 1


@pytest.mark.django_db
def test_expiration_erases_encrypted_material():
    company, user = _company_and_user()
    upload = CertificateUpload.objects.create(
        company=company,
        filename="empresa.pfx",
        encrypted_payload=b"encrypted-payload",
        encrypted_password=b"encrypted-password",
        uploaded_by=user,
        expires_at=timezone.now() - timedelta(seconds=1),
    )

    assert expire_staged_certificate_uploads() == 1

    upload.refresh_from_db()
    assert upload.status == CertificateUpload.Status.EXPIRED
    assert upload.encrypted_payload is None
    assert upload.encrypted_password is None


@pytest.mark.django_db
def test_worker_stores_hashed_password_and_client_scoped_encrypted_files(tmp_path):
    company, user = _company_and_user()
    password = "senha-secreta"
    payload = _valid_pkcs12(password)
    private_key = tmp_path / "upload-private.key"
    public_key = tmp_path / "upload-public.key"
    vault_key = tmp_path / "vault.key"
    vault_key.write_bytes(base64.urlsafe_b64encode(b"v" * 32))
    generate_upload_keypair(private_key_file=private_key, public_key_file=public_key)
    web_envelope = CertificateUploadEnvelope(public_key_file=public_key)
    worker_envelope = CertificateUploadEnvelope(
        public_key_file=public_key,
        private_key_file=private_key,
    )
    vault = CertificateVault(root=tmp_path / "certificates", key_file=vault_key)
    submission = stage_certificate_upload(
        company_id=company.pk,
        filename="empresa.pfx",
        payload=payload,
        password=password,
        uploaded_by=user,
        envelope=web_envelope,
        dispatch=False,
    )

    assert process_certificate_upload(
        submission.upload.pk,
        envelope=worker_envelope,
        vault=vault,
    ) == CertificateUpload.Status.COMPLETED

    submission.upload.refresh_from_db()
    certificate = submission.upload.certificate
    assert certificate is not None
    assert submission.upload.encrypted_payload is None
    assert submission.upload.encrypted_password is None
    assert certificate.password_hash != password
    assert password not in certificate.password_hash
    assert certificate.encrypted_path.startswith(
        f"clientes/{company.pk}/certificados/"
    )
    assert certificate.encrypted_password_path.startswith(
        f"clientes/{company.pk}/certificados/"
    )
    assert vault.load(certificate) == payload
    assert vault.unseal_password(certificate) == password
