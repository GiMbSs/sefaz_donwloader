"""Workstation permissions retained while replacing obsolete NSU operations."""

from datetime import time
from unittest.mock import patch

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from apps.accounts.models import User
from apps.fiscal.models import DownloadPolicy, DownloadRequest
from apps.operations.models import AuditLog
from apps.organizations.models import AccountingOffice, ClientCompany, OfficeMembership


@pytest.mark.parametrize("role", ["admin", "operator"])
def test_only_office_admin_can_configure_programmable_downloads(
    client, download_company, download_actor, role
):
    OfficeMembership.objects.filter(user=download_actor).update(role=role)
    policy = DownloadPolicy.objects.create(company=download_company)
    client.force_login(download_actor)
    response = client.post(
        reverse("company-policy", args=[download_company.pk]),
        {
            "mode": "automatic",
            "frequency": "weekly",
            "scheduled_time": "02:15",
            "timezone": "America/Fortaleza",
            "weekdays": ["1", "4"],
            "monthday": "1",
            "period_strategy": "rolling_days",
            "document_models": ["55", "65"],
            "rolling_days": "7",
            "formats": ["xml", "txt"],
            "is_active": "on",
        },
    )
    policy.refresh_from_db()
    if role == "admin":
        assert response.status_code == 302
        assert policy.is_active and policy.mode == "automatic"
        assert policy.weekdays == [1, 4]
        assert policy.scheduled_time == time(2, 15)
        assert AuditLog.objects.filter(
            action="fiscal.download_policy_updated", actor=download_actor
        ).exists()
        page = client.get(reverse("company-policy", args=[download_company.pk]))
        assert "auto_correct_nsu" not in page.context["form"].fields
    else:
        assert response.status_code == 404
        assert not policy.is_active


def test_operator_can_only_open_companies_from_their_office(
    client, download_company, download_actor
):
    other_office = AccountingOffice.objects.create(
        legal_name="Other", tax_identifier="11222333000181"
    )
    hidden = ClientCompany.objects.create(
        office=other_office, legal_name="Hidden", tax_identifier="11222333000181"
    )
    client.force_login(download_actor)
    assert (
        client.get(reverse("company-detail", args=[download_company.pk])).status_code
        == 200
    )
    assert client.get(reverse("company-detail", args=[hidden.pk])).status_code == 404
    assert (
        client.get(reverse("company-download-create", args=[hidden.pk])).status_code
        == 404
    )


def test_operator_can_enqueue_a_manual_period_request(
    client, download_company, download_actor
):
    client.force_login(download_actor)
    response = client.post(
        reverse("company-download-create", args=[download_company.pk]),
        {
            "start_date": "2024-10-01",
            "document_model": "55",
            "end_date": "2024-10-18",
            "formats": ["xml", "txt"],
        },
    )
    assert response.status_code == 302
    request = DownloadRequest.objects.get(company=download_company)
    assert request.status == "queued" and request.parts.count() == 2


def test_only_office_administrator_can_open_company_registration(
    client, download_actor
):
    client.force_login(download_actor)
    assert client.get(reverse("company-create")).status_code == 403


@pytest.mark.django_db
def test_superuser_can_create_first_office_and_is_made_administrator(client):
    user = User.objects.create_superuser(
        email="installation@example.test", password="test-password"
    )
    client.force_login(user)
    response = client.post(
        reverse("office-create"),
        {"legal_name": "Initial office", "tax_identifier": "00.000.000/0001-91"},
    )
    assert response.status_code == 302
    office = AccountingOffice.objects.get()
    assert OfficeMembership.objects.get(user=user, office=office).role == "admin"
    assert AuditLog.objects.filter(
        actor=user, action="organizations.office_created"
    ).exists()


@pytest.mark.django_db
def test_company_list_guides_superuser_through_first_office_registration(client):
    user = User.objects.create_superuser(
        email="installation@example.test", password="test-password"
    )
    client.force_login(user)
    response = client.get(reverse("company-list"))
    assert response.status_code == 200
    assert reverse("office-create").encode() in response.content


def test_non_superuser_cannot_create_an_office(client, download_actor):
    client.force_login(download_actor)
    assert client.get(reverse("office-create")).status_code == 403


def test_administrator_can_stage_certificate_during_company_registration(
    client, download_company, download_actor
):
    OfficeMembership.objects.filter(user=download_actor).update(role="admin")
    client.force_login(download_actor)
    with patch("apps.operations.views.stage_certificate_upload") as stage:
        response = client.post(
            reverse("company-create"),
            {
                "office": download_company.office_id,
                "legal_name": "Company with A1",
                "tax_identifier": "00000000E08G12",
                "state": "PB",
                "status": "active",
                "certificate_file": SimpleUploadedFile(
                    "synthetic.pfx", b"encrypted-upload-input"
                ),
                "certificate_password": "synthetic-password",
            },
        )
    assert response.status_code == 302
    company = ClientCompany.objects.get(legal_name="Company with A1")
    assert DownloadPolicy.objects.get(company=company).mode == "manual"
    stage.assert_called_once_with(
        company_id=company.pk,
        filename="synthetic.pfx",
        payload=b"encrypted-upload-input",
        password="synthetic-password",
        uploaded_by=download_actor,
    )
    payload = AuditLog.objects.get(action="organizations.company_created").payload
    assert payload["certificate_staged"]
    assert "synthetic-password" not in str(payload)


def test_company_registration_form_submits_certificate_as_multipart(
    client, download_company, download_actor
):
    OfficeMembership.objects.filter(user=download_actor).update(role="admin")
    client.force_login(download_actor)
    response = client.get(reverse("company-create"))
    assert response.status_code == 200 and response.context["form"].is_multipart()
    assert b'enctype="multipart/form-data"' in response.content


@pytest.mark.parametrize(
    "suffix", ["nsu/", "nsu-inicial/", "sincronizar/", "lotes/99/reprocessar/"]
)
def test_retired_nsu_and_soap_actions_cannot_start_a_new_query(
    client, download_company, download_actor, suffix
):
    client.force_login(download_actor)
    response = client.post(
        f"/empresas/{download_company.pk}/{suffix}", {"last_nsu": "123"}
    )
    assert response.status_code == 410
    assert not download_company.download_requests.exists()


def test_administrator_archives_company_after_explicit_cnpj_confirmation(
    client, download_company, download_actor
):
    OfficeMembership.objects.filter(user=download_actor).update(role="admin")
    policy = DownloadPolicy.objects.create(
        company=download_company, mode="hybrid", scheduled_time=time(2), is_active=True
    )
    client.force_login(download_actor)
    response = client.post(
        reverse("company-archive", args=[download_company.pk]),
        {
            "confirmation_tax_identifier": download_company.tax_identifier,
            "understand_retention": "on",
        },
    )
    assert response.status_code == 302
    download_company.refresh_from_db()
    policy.refresh_from_db()
    assert download_company.status == "archived" and not policy.is_active
    assert ClientCompany.objects.filter(pk=download_company.pk).exists()
    assert AuditLog.objects.filter(
        actor=download_actor, action="organizations.company_archived"
    ).exists()
