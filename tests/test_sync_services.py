from datetime import datetime, time
from unittest.mock import patch

import pytest
from django.utils import timezone

from apps.fiscal.models import NsuControl, SyncPolicy, SyncRequest
from apps.fiscal.services.sync import (
    SynchronizationRequestError,
    _dispatch_sync_request,
    enqueue_due_synchronizations,
    request_synchronization,
)
from apps.operations.models import AuditLog, OperationAlert
from apps.organizations.models import AccountingOffice, ClientCompany


def _company() -> ClientCompany:
    office = AccountingOffice.objects.create(
        legal_name="Contabilidade Exemplo Ltda.", tax_identifier="00000000000191"
    )
    return ClientCompany.objects.create(
        office=office,
        legal_name="Cliente Exemplo Ltda.",
        tax_identifier="00000000000191",
        fiscal_environment=ClientCompany.FiscalEnvironment.PRODUCTION,
    )


@pytest.mark.django_db
def test_manual_request_is_idempotent_and_does_not_accept_a_caller_nsu():
    company = _company()
    SyncPolicy.objects.create(
        company=company,
        mode=SyncPolicy.Mode.HYBRID,
        scheduled_time=time(2, 0),
    )

    first = request_synchronization(
        company_id=company.pk,
        environment=NsuControl.Environment.PRODUCTION,
        trigger=SyncRequest.Trigger.MANUAL,
    )
    repeated = request_synchronization(
        company_id=company.pk,
        environment=NsuControl.Environment.PRODUCTION,
        trigger=SyncRequest.Trigger.MANUAL,
    )

    assert first.created is True
    assert repeated.created is False
    assert repeated.request.pk == first.request.pk
    assert first.request.status == SyncRequest.Status.QUEUED
    assert NsuControl.objects.get(company=company).last_nsu == ""
    assert AuditLog.objects.filter(action="fiscal.sync_request_created").count() == 1


@pytest.mark.django_db
def test_queue_publish_failure_finishes_request_without_contacting_sefaz():
    company = _company()
    SyncPolicy.objects.create(
        company=company,
        mode=SyncPolicy.Mode.HYBRID,
        scheduled_time=time(2, 0),
    )
    submission = request_synchronization(
        company_id=company.pk,
        environment=NsuControl.Environment.PRODUCTION,
        trigger=SyncRequest.Trigger.MANUAL,
        dispatch=False,
    )

    with patch(
        "apps.fiscal.tasks.process_sync_request.delay",
        side_effect=RuntimeError("Redis indisponível"),
    ):
        _dispatch_sync_request(submission.request.pk)()

    submission.request.refresh_from_db()
    assert submission.request.status == SyncRequest.Status.FAILED
    assert "Nenhuma consulta foi enviada à SEFAZ" in submission.request.result_detail
    assert AuditLog.objects.filter(
        action="fiscal.sync_request_queue_unavailable",
        target=f"fiscal.sync_request:{submission.request.pk}",
    ).exists()
    alert = OperationAlert.objects.get(
        company=company,
        code="sync_queue_unavailable",
        status=OperationAlert.Status.OPEN,
    )
    assert alert.severity == OperationAlert.Severity.CRITICAL


@pytest.mark.django_db
def test_daily_policy_queues_once_inside_its_schedule_window():
    company = _company()
    policy = SyncPolicy.objects.create(
        company=company,
        mode=SyncPolicy.Mode.AUTOMATIC,
        scheduled_time=time(2, 0),
        timezone="America/Fortaleza",
        weekdays=[1],
    )
    now = timezone.make_aware(datetime(2026, 10, 6, 2, 10))

    assert enqueue_due_synchronizations(now=now) == 1
    assert enqueue_due_synchronizations(now=now) == 0

    policy.refresh_from_db()
    assert policy.last_requested_at == now


@pytest.mark.django_db
def test_daily_policy_rejects_manual_trigger():
    company = _company()
    SyncPolicy.objects.create(
        company=company,
        mode=SyncPolicy.Mode.AUTOMATIC,
        scheduled_time=time(2, 0),
    )

    with pytest.raises(
        SynchronizationRequestError,
        match="somente sincronização automática",
    ):
        request_synchronization(
            company_id=company.pk,
            environment=NsuControl.Environment.PRODUCTION,
            trigger=SyncRequest.Trigger.MANUAL,
        )


@pytest.mark.django_db
def test_weekly_policy_uses_company_environment_and_queues_once_per_week():
    company = _company()
    policy = SyncPolicy.objects.create(
        company=company,
        mode=SyncPolicy.Mode.AUTOMATIC,
        frequency=SyncPolicy.Frequency.WEEKLY,
        scheduled_time=time(2, 0),
        timezone="America/Fortaleza",
        weekdays=[2],
    )
    now = timezone.make_aware(datetime(2026, 10, 7, 2, 10))

    assert enqueue_due_synchronizations(now=now) == 1
    assert enqueue_due_synchronizations(now=now) == 0

    request = SyncRequest.objects.get(company=company)
    assert request.environment == ClientCompany.FiscalEnvironment.PRODUCTION
    policy.refresh_from_db()
    assert policy.last_requested_at == now


@pytest.mark.django_db
def test_monthly_policy_uses_last_calendar_day_when_configured_day_is_unavailable():
    company = _company()
    SyncPolicy.objects.create(
        company=company,
        mode=SyncPolicy.Mode.AUTOMATIC,
        frequency=SyncPolicy.Frequency.MONTHLY,
        scheduled_time=time(2, 0),
        timezone="America/Fortaleza",
        monthday=31,
    )
    last_day_of_february = timezone.make_aware(datetime(2026, 2, 28, 2, 10))

    assert enqueue_due_synchronizations(now=last_day_of_february) == 1


@pytest.mark.django_db
def test_request_rejects_an_environment_other_than_the_company_configuration():
    company = _company()
    SyncPolicy.objects.create(
        company=company,
        mode=SyncPolicy.Mode.HYBRID,
        scheduled_time=time(2, 0),
    )

    with pytest.raises(SynchronizationRequestError, match="ambiente definido"):
        request_synchronization(
            company_id=company.pk,
            environment=NsuControl.Environment.HOMOLOGATION,
            trigger=SyncRequest.Trigger.MANUAL,
        )
