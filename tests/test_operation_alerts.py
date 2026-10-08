import pytest
from django.urls import reverse

from apps.accounts.models import User
from apps.operations.models import AuditLog, OperationAlert
from apps.operations.services import open_operation_alert
from apps.organizations.models import AccountingOffice, ClientCompany, OfficeMembership


def _company(name: str, tax_identifier: str) -> ClientCompany:
    office = AccountingOffice.objects.create(
        legal_name=f"{name} Contabilidade Ltda.",
        tax_identifier=tax_identifier,
    )
    return ClientCompany.objects.create(
        office=office,
        legal_name=f"{name} Cliente Ltda.",
        tax_identifier=tax_identifier,
    )


@pytest.mark.django_db
def test_open_alert_refreshes_one_unresolved_alert_per_company_and_code():
    company = _company("Primeira", "00000000000191")

    first = open_operation_alert(
        company_id=company.pk,
        code="sync_execution_failed",
        severity=OperationAlert.Severity.CRITICAL,
        title="Sincronização fiscal não concluída",
        message="A comunicação não foi confirmada.",
        context={"reason": "transport"},
    )
    repeated = open_operation_alert(
        company_id=company.pk,
        code="sync_execution_failed",
        severity=OperationAlert.Severity.WARNING,
        title="Sincronização fiscal ainda pendente",
        message="Aguarde a janela de segurança.",
        context={"reason": "waiting"},
    )

    assert first.created is True
    assert repeated.created is False
    assert OperationAlert.objects.filter(company=company).count() == 1
    repeated.alert.refresh_from_db()
    assert repeated.alert.severity == OperationAlert.Severity.WARNING
    assert repeated.alert.message == "Aguarde a janela de segurança."
    assert repeated.alert.context == {"reason": "waiting"}


@pytest.mark.django_db
def test_operator_only_sees_alerts_for_their_own_office(client):
    user = User.objects.create_user(
        email="operador@example.test",
        password="senha-segura",
    )
    visible_company = _company("Visível", "00000000000191")
    hidden_company = _company("Restrita", "00000000E08G12")
    OfficeMembership.objects.create(
        office=visible_company.office,
        user=user,
        role=OfficeMembership.Role.OPERATOR,
    )
    visible_alert = OperationAlert.objects.create(
        company=visible_company,
        code="visible",
        severity=OperationAlert.Severity.WARNING,
        title="Alerta visível",
        message="Revisar a fila.",
    )
    OperationAlert.objects.create(
        company=hidden_company,
        code="hidden",
        severity=OperationAlert.Severity.CRITICAL,
        title="Alerta restrito",
        message="Não deve aparecer.",
    )
    client.force_login(user)

    response = client.get(reverse("alert-list"))
    resolve_response = client.post(
        reverse("alert-resolve", args=[visible_alert.pk]),
        {"resolution_note": "Tentativa não autorizada."},
    )

    assert response.status_code == 200
    assert b"Alerta vis\xc3\xadvel" in response.content
    assert b"Alerta restrito" not in response.content
    assert resolve_response.status_code == 404
    visible_alert.refresh_from_db()
    assert visible_alert.status == OperationAlert.Status.OPEN


@pytest.mark.django_db
def test_office_administrator_resolves_alert_with_an_audit_record(client):
    user = User.objects.create_user(
        email="admin@example.test",
        password="senha-segura",
    )
    company = _company("Administrável", "00000000000191")
    OfficeMembership.objects.create(
        office=company.office,
        user=user,
        role=OfficeMembership.Role.ADMIN,
    )
    alert = OperationAlert.objects.create(
        company=company,
        code="sync_execution_failed",
        severity=OperationAlert.Severity.CRITICAL,
        title="Sincronização fiscal não concluída",
        message="Revisar conexão.",
    )
    client.force_login(user)

    response = client.post(
        reverse("alert-resolve", args=[alert.pk]),
        {"resolution_note": "Conexão revisada e nova solicitação liberada."},
    )

    assert response.status_code == 302
    alert.refresh_from_db()
    assert alert.status == OperationAlert.Status.RESOLVED
    assert alert.resolved_by == user
    assert alert.resolution_note == "Conexão revisada e nova solicitação liberada."
    assert AuditLog.objects.filter(
        action="operations.alert_resolved",
        target=f"operations.alert:{alert.pk}",
        actor=user,
    ).exists()
