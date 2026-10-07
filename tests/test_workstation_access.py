from datetime import time

import pytest
from django.urls import reverse

from apps.accounts.models import User
from apps.fiscal.models import NsuControl, SyncPolicy, SyncRequest
from apps.organizations.models import AccountingOffice, ClientCompany, OfficeMembership


def _office(name: str, tax_identifier: str) -> AccountingOffice:
    return AccountingOffice.objects.create(
        legal_name=name,
        tax_identifier=tax_identifier,
    )


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
    assert hidden.status_code == 404


@pytest.mark.django_db
def test_operator_can_enqueue_a_manual_request_without_exposing_nsu(client):
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
    SyncPolicy.objects.create(
        company=company,
        mode=SyncPolicy.Mode.HYBRID,
        scheduled_time=time(2, 0),
    )
    client.force_login(user)

    response = client.post(
        reverse("company-sync", args=[company.pk]),
        {"environment": NsuControl.Environment.PRODUCTION},
    )

    assert response.status_code == 302
    assert (
        SyncRequest.objects.filter(
            company=company,
            status=SyncRequest.Status.QUEUED,
        ).count()
        == 1
    )
    assert NsuControl.objects.get(company=company).last_nsu == ""


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
