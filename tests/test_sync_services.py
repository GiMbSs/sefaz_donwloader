from datetime import datetime, time

import pytest
from django.utils import timezone

from apps.fiscal.models import NsuControl, SyncPolicy, SyncRequest
from apps.fiscal.services.sync import (
    SynchronizationRequestError,
    enqueue_due_synchronizations,
    request_synchronization,
)
from apps.operations.models import AuditLog
from apps.organizations.models import AccountingOffice, ClientCompany


def _company() -> ClientCompany:
    office = AccountingOffice.objects.create(
        legal_name="Contabilidade Exemplo Ltda.", tax_identifier="00000000000191"
    )
    return ClientCompany.objects.create(
        office=office,
        legal_name="Cliente Exemplo Ltda.",
        tax_identifier="00000000000191",
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
def test_daily_policy_queues_once_inside_its_schedule_window():
    company = _company()
    policy = SyncPolicy.objects.create(
        company=company,
        mode=SyncPolicy.Mode.DAILY,
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
        mode=SyncPolicy.Mode.DAILY,
        scheduled_time=time(2, 0),
    )

    with pytest.raises(SynchronizationRequestError, match="somente sincronização diária"):
        request_synchronization(
            company_id=company.pk,
            environment=NsuControl.Environment.PRODUCTION,
            trigger=SyncRequest.Trigger.MANUAL,
        )
