from datetime import time, timedelta
from unittest.mock import patch

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.fiscal.models import DistributionBatch, NsuControl, SyncPolicy, SyncRequest
from apps.operations.models import AuditLog
from apps.organizations.models import AccountingOffice, ClientCompany, OfficeMembership


def _office(name: str, tax_identifier: str) -> AccountingOffice:
    return AccountingOffice.objects.create(
        legal_name=name,
        tax_identifier=tax_identifier,
    )


@pytest.mark.django_db
@pytest.mark.parametrize(
    "role", [OfficeMembership.Role.ADMIN, OfficeMembership.Role.OPERATOR]
)
def test_only_office_admin_can_enable_automatic_nsu_correction(client, role):
    user = User.objects.create_user(email="nsu@example.test", password="senha-segura")
    office = _office("Contabilidade", "00000000000191")
    company = ClientCompany.objects.create(
        office=office, legal_name="Cliente", tax_identifier="00000000000191"
    )
    OfficeMembership.objects.create(office=office, user=user, role=role)
    policy = SyncPolicy.objects.create(company=company, mode=SyncPolicy.Mode.MANUAL)
    assert policy.auto_correct_nsu is False
    client.force_login(user)
    response = client.post(
        reverse("company-policy", args=[company.pk]),
        {
            "mode": "manual",
            "frequency": "daily",
            "timezone": "America/Fortaleza",
            "monthday": "1",
            "is_active": "on",
            "auto_correct_nsu": "on",
        },
    )
    policy.refresh_from_db()
    if role == OfficeMembership.Role.ADMIN:
        assert response.status_code == 302
        assert policy.auto_correct_nsu is True
        assert (
            AuditLog.objects.get(action="fiscal.sync_policy_updated").payload[
                "auto_correct_nsu"
            ]
            is True
        )
        page = client.get(reverse("company-policy", args=[company.pk]))
        assert b"auto_correct_nsu" in page.content
    else:
        assert response.status_code == 404
        assert policy.auto_correct_nsu is False


@pytest.mark.django_db
def test_operator_can_only_open_companies_from_their_office(client):
    user = User.objects.create_user(
        email="operador@example.test",
        password="senha-segura",
    )
    first_office = _office("Contabilidade Um Ltda.", "00000000000191")
    second_office = _office("Contabilidade Dois Ltda.", "00000000E08G12")
    first_company = ClientCompany.objects.create(
        office=first_office,
        legal_name="Cliente Visível Ltda.",
        tax_identifier="00000000000191",
    )
    hidden_company = ClientCompany.objects.create(
        office=second_office,
        legal_name="Cliente Restrito Ltda.",
        tax_identifier="00000000000191",
    )
    OfficeMembership.objects.create(
        office=first_office,
        user=user,
        role=OfficeMembership.Role.OPERATOR,
    )
    client.force_login(user)

    visible = client.get(reverse("company-detail", args=[first_company.pk]))
    hidden = client.get(reverse("company-detail", args=[hidden_company.pk]))

    assert visible.status_code == 200
    assert b"Ambiente cadastrado" in visible.content
    assert hidden.status_code == 404


@pytest.mark.django_db
@pytest.mark.parametrize(
    "environment",
    (
        NsuControl.Environment.PRODUCTION,
        NsuControl.Environment.HOMOLOGATION,
    ),
)
def test_operator_can_enqueue_a_manual_request_without_exposing_nsu(
    client, environment: str
):
    user = User.objects.create_user(
        email="operador@example.test",
        password="senha-segura",
    )
    office = _office("Contabilidade Um Ltda.", "00000000000191")
    company = ClientCompany.objects.create(
        office=office,
        legal_name="Cliente Visível Ltda.",
        tax_identifier="00000000000191",
        fiscal_environment=environment,
    )
    OfficeMembership.objects.create(
        office=office,
        user=user,
        role=OfficeMembership.Role.OPERATOR,
    )
    SyncPolicy.objects.create(
        company=company,
        mode=SyncPolicy.Mode.HYBRID,
        scheduled_time=time(2, 0),
    )
    client.force_login(user)

    response = client.post(
        reverse("company-sync", args=[company.pk]),
        {"environment": environment},
    )

    assert response.status_code == 302
    assert (
        SyncRequest.objects.filter(
            company=company,
            status=SyncRequest.Status.QUEUED,
        ).count()
        == 1
    )
    assert (
        NsuControl.objects.get(
            company=company,
            environment=environment,
        ).last_nsu
        == ""
    )


@pytest.mark.django_db
def test_only_office_administrator_can_open_company_registration(client):
    user = User.objects.create_user(
        email="operador@example.test",
        password="senha-segura",
    )
    office = _office("Contabilidade Um Ltda.", "00000000000191")
    OfficeMembership.objects.create(
        office=office,
        user=user,
        role=OfficeMembership.Role.OPERATOR,
    )
    client.force_login(user)

    response = client.get(reverse("company-create"))

    assert response.status_code == 403


@pytest.mark.django_db
def test_superuser_can_create_first_office_and_is_made_administrator(client):
    user = User.objects.create_superuser(
        email="instalacao@example.test",
        password="senha-segura",
    )
    client.force_login(user)

    response = client.post(
        reverse("office-create"),
        {
            "legal_name": "Contabilidade Inicial Ltda.",
            "tax_identifier": "00.000.000/0001-91",
        },
    )

    office = AccountingOffice.objects.get(legal_name="Contabilidade Inicial Ltda.")
    membership = OfficeMembership.objects.get(office=office, user=user)
    assert response.status_code == 302
    assert response.url == reverse("company-create")
    assert office.tax_identifier == "00000000000191"
    assert membership.role == OfficeMembership.Role.ADMIN
    assert membership.is_active is True
    assert AuditLog.objects.filter(
        actor=user,
        action="organizations.office_created",
        target=f"organizations.accounting_office:{office.pk}",
    ).exists()


@pytest.mark.django_db
def test_company_list_guides_superuser_through_first_office_registration(client):
    user = User.objects.create_superuser(
        email="instalacao@example.test",
        password="senha-segura",
    )
    client.force_login(user)

    response = client.get(reverse("company-list"))

    assert response.status_code == 200
    assert b"Cadastrar escrit\xc3\xb3rio cont\xc3\xa1bil" in response.content
    assert reverse("office-create").encode() in response.content


@pytest.mark.django_db
def test_non_superuser_cannot_create_an_office(client):
    user = User.objects.create_user(
        email="admin-escritorio@example.test",
        password="senha-segura",
    )
    client.force_login(user)

    response = client.get(reverse("office-create"))

    assert response.status_code == 403


@pytest.mark.django_db
def test_administrator_can_stage_certificate_during_company_registration(client):
    user = User.objects.create_user(
        email="admin@example.test",
        password="senha-segura",
    )
    office = _office("Contabilidade Um Ltda.", "00000000000191")
    OfficeMembership.objects.create(
        office=office,
        user=user,
        role=OfficeMembership.Role.ADMIN,
    )
    client.force_login(user)

    with patch("apps.operations.views.stage_certificate_upload") as stage_upload:
        response = client.post(
            reverse("company-create"),
            {
                "office": office.pk,
                "legal_name": "Cliente com A1 Ltda.",
                "tax_identifier": "00000000E08G12",
                "state_registration": "",
                "state": "PB",
                "fiscal_environment": ClientCompany.FiscalEnvironment.HOMOLOGATION,
                "status": ClientCompany.Status.ACTIVE,
                "certificate_file": SimpleUploadedFile(
                    "cliente.pfx",
                    b"certificate-upload-envelope-input",
                    content_type="application/x-pkcs12",
                ),
                "certificate_password": "senha-do-certificado",
            },
        )

    company = ClientCompany.objects.get(legal_name="Cliente com A1 Ltda.")
    policy = SyncPolicy.objects.get(company=company)
    assert response.status_code == 302
    assert policy.is_active is False
    stage_upload.assert_called_once_with(
        company_id=company.pk,
        filename="cliente.pfx",
        payload=b"certificate-upload-envelope-input",
        password="senha-do-certificado",
        uploaded_by=user,
    )
    audit_payload = AuditLog.objects.get(
        action="organizations.company_created",
        target=f"organizations.client_company:{company.pk}",
    ).payload
    assert audit_payload["certificate_staged"] is True
    assert "senha-do-certificado" not in str(audit_payload)


@pytest.mark.django_db
def test_company_registration_form_submits_certificate_as_multipart(client):
    user = User.objects.create_user(
        email="admin@example.test",
        password="senha-segura",
    )
    office = _office("Contabilidade Um Ltda.", "00000000000191")
    OfficeMembership.objects.create(
        office=office,
        user=user,
        role=OfficeMembership.Role.ADMIN,
    )
    client.force_login(user)

    response = client.get(reverse("company-create"))

    assert response.status_code == 200
    assert response.context["form"].is_multipart()
    assert b'enctype="multipart/form-data"' in response.content


@pytest.mark.django_db
def test_administrator_can_set_an_initial_nsu_during_company_registration(client):
    user = User.objects.create_user(
        email="admin@example.test",
        password="senha-segura",
    )
    office = _office("Contabilidade Um Ltda.", "00000000000191")
    OfficeMembership.objects.create(
        office=office,
        user=user,
        role=OfficeMembership.Role.ADMIN,
    )
    client.force_login(user)

    response = client.post(
        reverse("company-create"),
        {
            "office": office.pk,
            "legal_name": "Cliente com histórico Ltda.",
            "tax_identifier": "00000000E08G12",
            "state_registration": "",
            "state": "PB",
            "fiscal_environment": ClientCompany.FiscalEnvironment.HOMOLOGATION,
            "initial_nsu": "12345",
            "status": ClientCompany.Status.ACTIVE,
        },
    )

    company = ClientCompany.objects.get(legal_name="Cliente com histórico Ltda.")
    control = NsuControl.objects.get(company=company)
    assert response.status_code == 302
    assert control.environment == NsuControl.Environment.HOMOLOGATION
    assert control.last_nsu == "000000000012345"
    assert AuditLog.objects.filter(
        actor=user,
        action="fiscal.initial_nsu_configured",
        target=f"fiscal.nsu_control:{control.pk}",
    ).exists()


@pytest.mark.django_db
def test_administrator_can_correct_nsu_after_fiscal_history(client):
    user = User.objects.create_user(
        email="admin@example.test",
        password="senha-segura",
    )
    office = _office("Contabilidade Um Ltda.", "00000000000191")
    company = ClientCompany.objects.create(
        office=office,
        legal_name="Cliente existente Ltda.",
        tax_identifier="00000000E08G12",
        fiscal_environment=ClientCompany.FiscalEnvironment.HOMOLOGATION,
    )
    OfficeMembership.objects.create(
        office=office,
        user=user,
        role=OfficeMembership.Role.ADMIN,
    )
    hold_until = timezone.now() + timedelta(hours=1)
    control = NsuControl.objects.create(
        company=company,
        environment=NsuControl.Environment.HOMOLOGATION,
        last_nsu="000000000000001",
        next_allowed_at=hold_until,
        last_status_code="656",
    )
    SyncRequest.objects.create(
        company=company,
        environment=NsuControl.Environment.HOMOLOGATION,
        trigger=SyncRequest.Trigger.MANUAL,
        status=SyncRequest.Status.SUCCEEDED,
    )
    client.force_login(user)

    response = client.post(
        reverse("company-nsu-cursor", args=[company.pk]),
        {
            "last_nsu": "987654321",
            "confirmation_tax_identifier": company.tax_identifier,
            "reason": "Correção com base no cursor informado pela contabilidade.",
            "understand_consequences": "on",
        },
    )

    control.refresh_from_db()
    assert response.status_code == 302
    assert response.url == reverse("company-detail", args=[company.pk])
    assert control.last_nsu == "000000987654321"
    assert control.next_allowed_at == hold_until
    assert control.last_status_code == "656"
    assert AuditLog.objects.filter(
        actor=user,
        action="fiscal.nsu_cursor_corrected",
        target=f"fiscal.nsu_control:{control.pk}",
        payload={
            "company_id": company.pk,
            "environment": NsuControl.Environment.HOMOLOGATION,
            "service": "nfe_distribution",
            "previous_last_nsu": "000000000000001",
            "new_last_nsu": "000000987654321",
            "reason": "Correção com base no cursor informado pela contabilidade.",
        },
    ).exists()


@pytest.mark.django_db
def test_operator_cannot_open_the_nsu_cursor_correction(client):
    user = User.objects.create_user(
        email="operador@example.test",
        password="senha-segura",
    )
    office = _office("Contabilidade Um Ltda.", "00000000000191")
    company = ClientCompany.objects.create(
        office=office,
        legal_name="Cliente Visível Ltda.",
        tax_identifier="00000000000191",
    )
    OfficeMembership.objects.create(
        office=office,
        user=user,
        role=OfficeMembership.Role.OPERATOR,
    )
    client.force_login(user)

    response = client.get(reverse("company-nsu-cursor", args=[company.pk]))

    assert response.status_code == 404


@pytest.mark.django_db
def test_administrator_can_queue_a_failed_batch_for_local_reprocessing(client):
    user = User.objects.create_user(
        email="admin@example.test",
        password="senha-segura",
    )
    office = _office("Contabilidade Um Ltda.", "00000000000191")
    company = ClientCompany.objects.create(
        office=office,
        legal_name="Cliente Visível Ltda.",
        tax_identifier="00000000000191",
    )
    OfficeMembership.objects.create(
        office=office,
        user=user,
        role=OfficeMembership.Role.ADMIN,
    )
    control = NsuControl.objects.create(
        company=company,
        environment=NsuControl.Environment.PRODUCTION,
    )
    batch = DistributionBatch.objects.create(
        company=company,
        nsu_control=control,
        response_sha256="a" * 64,
        raw_response_path="_lotes/1/distribution-test.xml",
        status_code="138",
        processing_status=DistributionBatch.ProcessingStatus.FAILED,
        processing_error="Falha local simulada.",
    )
    client.force_login(user)

    response = client.post(reverse("batch-reprocess", args=[company.pk, batch.pk]))

    batch.refresh_from_db()
    assert response.status_code == 302
    assert batch.processing_status == DistributionBatch.ProcessingStatus.RECEIVED
    assert AuditLog.objects.filter(
        actor=user,
        action="fiscal.distribution_batch_reprocess_requested",
        target=f"fiscal.distribution_batch:{batch.pk}",
    ).exists()


@pytest.mark.django_db
def test_operator_cannot_queue_a_failed_batch_for_local_reprocessing(client):
    user = User.objects.create_user(
        email="operador@example.test",
        password="senha-segura",
    )
    office = _office("Contabilidade Um Ltda.", "00000000000191")
    company = ClientCompany.objects.create(
        office=office,
        legal_name="Cliente Visível Ltda.",
        tax_identifier="00000000000191",
    )
    OfficeMembership.objects.create(
        office=office,
        user=user,
        role=OfficeMembership.Role.OPERATOR,
    )
    control = NsuControl.objects.create(
        company=company,
        environment=NsuControl.Environment.PRODUCTION,
    )
    batch = DistributionBatch.objects.create(
        company=company,
        nsu_control=control,
        response_sha256="a" * 64,
        raw_response_path="_lotes/1/distribution-test.xml",
        status_code="138",
        processing_status=DistributionBatch.ProcessingStatus.FAILED,
        processing_error="Falha local simulada.",
    )
    client.force_login(user)

    response = client.post(reverse("batch-reprocess", args=[company.pk, batch.pk]))

    batch.refresh_from_db()
    assert response.status_code == 404
    assert batch.processing_status == DistributionBatch.ProcessingStatus.FAILED
    assert not AuditLog.objects.filter(
        action="fiscal.distribution_batch_reprocess_requested"
    ).exists()


@pytest.mark.django_db
def test_administrator_archives_company_after_explicit_cnpj_confirmation(client):
    user = User.objects.create_user(
        email="admin@example.test",
        password="senha-segura",
    )
    office = _office("Contabilidade Um Ltda.", "00000000000191")
    company = ClientCompany.objects.create(
        office=office,
        legal_name="Cliente Arquivado Ltda.",
        tax_identifier="00000000000191",
    )
    policy = SyncPolicy.objects.create(
        company=company,
        mode=SyncPolicy.Mode.HYBRID,
        scheduled_time=time(2, 0),
    )
    OfficeMembership.objects.create(
        office=office,
        user=user,
        role=OfficeMembership.Role.ADMIN,
    )
    client.force_login(user)

    response = client.post(
        reverse("company-archive", args=[company.pk]),
        {
            "confirmation_tax_identifier": company.tax_identifier,
            "understand_retention": "on",
        },
    )

    company.refresh_from_db()
    policy.refresh_from_db()
    assert response.status_code == 302
    assert company.status == ClientCompany.Status.ARCHIVED
    assert policy.is_active is False
    assert AuditLog.objects.filter(
        actor=user,
        action="organizations.company_archived",
        target=f"organizations.client_company:{company.pk}",
    ).exists()
