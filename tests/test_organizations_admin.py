import pytest
from django.contrib import admin
from django.contrib.auth.models import Permission
from django.test import RequestFactory
from django.urls import reverse

from apps.accounts.models import User
from apps.fiscal.models import NsuControl
from apps.operations.models import AuditLog
from apps.organizations.models import AccountingOffice, ClientCompany, OfficeMembership


def _company() -> ClientCompany:
    office = AccountingOffice.objects.create(
        legal_name="Contabilidade Exemplo Ltda.",
        tax_identifier="00000000000191",
    )
    return ClientCompany.objects.create(
        office=office,
        legal_name="Cliente em Homologação Ltda.",
        tax_identifier="00000000000191",
        fiscal_environment=ClientCompany.FiscalEnvironment.HOMOLOGATION,
    )


def _admin_user() -> User:
    user = User.objects.create_user(
        email="admin@example.com",
        password="senha-segura",
        is_staff=True,
    )
    permission = Permission.objects.get(
        content_type__app_label="organizations",
        codename="change_clientcompany",
    )
    user.user_permissions.add(permission)
    return user


@pytest.mark.django_db
def test_django_admin_promotes_homologation_without_deleting_its_history(client):
    company = _company()
    NsuControl.objects.create(
        company=company,
        environment=NsuControl.Environment.HOMOLOGATION,
        last_nsu="000000000012345",
    )
    user = _admin_user()
    OfficeMembership.objects.create(office=company.office, user=user, role="admin")
    client.force_login(user)
    changelist_url = reverse("admin:organizations_clientcompany_changelist")

    confirmation = client.post(
        changelist_url,
        {
            "action": "promote_to_production",
            "_selected_action": company.pk,
        },
    )

    assert confirmation.status_code == 200
    assert "Confirmar promoção para Produção" in confirmation.content.decode()
    company.refresh_from_db()
    assert company.fiscal_environment == ClientCompany.FiscalEnvironment.HOMOLOGATION

    result = client.post(
        changelist_url,
        {
            "action": "promote_to_production",
            "confirm_promotion": "yes",
            "_selected_action": company.pk,
        },
    )

    assert result.status_code == 302
    company.refresh_from_db()
    assert company.fiscal_environment == ClientCompany.FiscalEnvironment.PRODUCTION
    assert NsuControl.objects.filter(
        company=company,
        environment=NsuControl.Environment.HOMOLOGATION,
        last_nsu="000000000012345",
    ).exists()
    assert AuditLog.objects.filter(
        actor=user,
        action="organizations.fiscal_environment_promoted",
        target=f"organizations.client_company:{company.pk}",
        payload={
            "from_environment": ClientCompany.FiscalEnvironment.HOMOLOGATION,
            "to_environment": ClientCompany.FiscalEnvironment.PRODUCTION,
            "source": "django_admin",
        },
    ).exists()


@pytest.mark.django_db
def test_django_admin_hides_promotion_action_without_change_permission():
    user = User.objects.create_user(
        email="operator@example.com",
        password="senha-segura",
        is_staff=True,
    )
    request = RequestFactory().get("/admin/organizations/clientcompany/")
    request.user = user
    model_admin = admin.site._registry[ClientCompany]

    assert "promote_to_production" not in model_admin.get_actions(request)
