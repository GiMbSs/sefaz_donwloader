"""Use cases for creating safe, idempotent DF-e synchronization requests."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from calendar import monthrange
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from django.db import transaction
from django.utils import timezone

from apps.fiscal.models import NsuControl, SyncPolicy, SyncRequest
from apps.operations.models import AuditLog
from apps.organizations.models import ClientCompany

if TYPE_CHECKING:
    from apps.accounts.models import User


class SynchronizationRequestError(ValueError):
    """A request could not be accepted without violating fiscal safeguards."""


@dataclass(frozen=True)
class SyncRequestSubmission:
    request: SyncRequest
    created: bool


def request_synchronization(
    *,
    company_id: int,
    environment: str,
    trigger: str,
    actor: User | None = None,
    now: datetime | None = None,
    dispatch: bool = True,
) -> SyncRequestSubmission:
    """Create one pending request or return the existing active request.

    The NSU value is deliberately never accepted from callers. It remains owned
    by ``NsuControl`` and can only move after a successfully persisted response.
    """
    now = now or timezone.now()
    if environment not in NsuControl.Environment.values:
        raise SynchronizationRequestError("Ambiente fiscal inválido.")
    if trigger not in SyncRequest.Trigger.values:
        raise SynchronizationRequestError("Origem da solicitação inválida.")

    with transaction.atomic():
        company = ClientCompany.objects.select_for_update().filter(pk=company_id).first()
        if company is None:
            raise SynchronizationRequestError("Empresa cliente não encontrada.")
        if company.status != ClientCompany.Status.ACTIVE:
            raise SynchronizationRequestError("A empresa não está ativa para sincronização.")
        if environment != company.fiscal_environment:
            raise SynchronizationRequestError(
                "A solicitação deve usar o ambiente definido no cadastro da empresa."
            )

        policy = SyncPolicy.objects.select_for_update().filter(company=company).first()
        if policy is None or not policy.is_active:
            raise SynchronizationRequestError("A política de sincronização está desativada.")
        _ensure_trigger_allowed(policy, trigger)

        control, _ = NsuControl.objects.get_or_create(
            company=company,
            environment=environment,
            service="nfe_distribution",
        )
        existing = (
            SyncRequest.objects.select_for_update()
            .filter(
                company=company,
                environment=environment,
                status__in=(
                    SyncRequest.Status.QUEUED,
                    SyncRequest.Status.RUNNING,
                    SyncRequest.Status.WAITING,
                ),
            )
            .order_by("requested_at")
            .first()
        )
        if existing is not None:
            if dispatch and existing.status == SyncRequest.Status.QUEUED:
                transaction.on_commit(_dispatch_sync_request(existing.pk))
            return SyncRequestSubmission(request=existing, created=False)

        is_blocked = control.next_allowed_at is not None and control.next_allowed_at > now
        request = SyncRequest.objects.create(
            company=company,
            environment=environment,
            trigger=trigger,
            status=SyncRequest.Status.WAITING if is_blocked else SyncRequest.Status.QUEUED,
            requested_by=actor,
            result_detail=(
                f"Consulta permitida após {control.next_allowed_at.isoformat()}."
                if is_blocked
                else ""
            ),
        )
        policy.last_requested_at = now
        policy.save(update_fields=("last_requested_at", "updated_at"))
        AuditLog.objects.create(
            actor=actor,
            action="fiscal.sync_request_created",
            target=f"fiscal.sync_request:{request.pk}",
            payload={
                "company_id": company.pk,
                "environment": environment,
                "trigger": trigger,
                "status": request.status,
            },
        )
        if dispatch and request.status == SyncRequest.Status.QUEUED:
            transaction.on_commit(_dispatch_sync_request(request.pk))
        return SyncRequestSubmission(request=request, created=True)


def enqueue_due_synchronizations(*, now: datetime | None = None) -> int:
    """Queue due automatic policies once, regardless of Beat's polling cadence."""
    now = now or timezone.now()
    queued = _release_waiting_synchronizations(now=now)
    due_policies = SyncPolicy.objects.select_related("company").filter(
        is_active=True,
        company__status=ClientCompany.Status.ACTIVE,
        mode__in=(SyncPolicy.Mode.AUTOMATIC, SyncPolicy.Mode.HYBRID),
    )
    for policy in due_policies.iterator():
        if not _is_due(policy, now):
            continue
        submission = request_synchronization(
            company_id=policy.company_id,
            environment=policy.company.fiscal_environment,
            trigger=SyncRequest.Trigger.SCHEDULED,
            now=now,
        )
        queued += int(submission.created)
    return queued


def _release_waiting_synchronizations(*, now: datetime) -> int:
    """Resume requests only after the persisted SEFAZ wait expires."""
    released = 0
    with transaction.atomic():
        controls = list(
            NsuControl.objects.select_for_update()
            .filter(
                service="nfe_distribution",
                next_allowed_at__isnull=False,
                next_allowed_at__lte=now,
            )
            .only("pk", "company_id", "environment")
        )
        for control in controls:
            sync_request = (
                SyncRequest.objects.select_for_update()
                .filter(
                    company_id=control.company_id,
                    environment=control.environment,
                    status=SyncRequest.Status.WAITING,
                )
                .order_by("requested_at")
                .first()
            )
            if sync_request is None:
                continue
            sync_request.status = SyncRequest.Status.QUEUED
            sync_request.result_detail = "Consulta liberada pela janela fiscal."
            sync_request.save(update_fields=("status", "result_detail"))
            AuditLog.objects.create(
                actor=sync_request.requested_by,
                action="fiscal.sync_request_released",
                target=f"fiscal.sync_request:{sync_request.pk}",
                payload={
                    "company_id": sync_request.company_id,
                    "environment": sync_request.environment,
                },
            )
            transaction.on_commit(_dispatch_sync_request(sync_request.pk))
            released += 1
    return released


def _dispatch_sync_request(sync_request_id: int) -> Callable[[], None]:
    def dispatch() -> None:
        from apps.fiscal.tasks import process_sync_request

        process_sync_request.delay(sync_request_id)

    return dispatch


def _ensure_trigger_allowed(policy: SyncPolicy, trigger: str) -> None:
    if trigger == SyncRequest.Trigger.MANUAL and policy.mode == SyncPolicy.Mode.AUTOMATIC:
        raise SynchronizationRequestError(
            "A política atual permite somente sincronização automática."
        )
    if trigger == SyncRequest.Trigger.SCHEDULED and policy.mode == SyncPolicy.Mode.MANUAL:
        raise SynchronizationRequestError(
            "A política atual permite somente solicitações manuais."
        )


def _is_due(policy: SyncPolicy, now: datetime) -> bool:
    if policy.scheduled_time is None:
        return False
    try:
        policy_timezone = ZoneInfo(policy.timezone)
    except Exception:
        return False
    local_now = now.astimezone(policy_timezone)
    if policy.frequency == SyncPolicy.Frequency.WEEKLY:
        if local_now.weekday() not in policy.weekdays:
            return False
    elif policy.frequency == SyncPolicy.Frequency.MONTHLY:
        last_day = monthrange(local_now.year, local_now.month)[1]
        if local_now.day != min(policy.monthday, last_day):
            return False
    scheduled_at = local_now.replace(
        hour=policy.scheduled_time.hour,
        minute=policy.scheduled_time.minute,
        second=0,
        microsecond=0,
    )
    grace_period = timedelta(minutes=30)
    if not scheduled_at <= local_now < scheduled_at + grace_period:
        return False
    if policy.last_requested_at is None:
        return True
    previous_local = policy.last_requested_at.astimezone(policy_timezone)
    if policy.frequency == SyncPolicy.Frequency.DAILY:
        return previous_local.date() != local_now.date()
    if policy.frequency == SyncPolicy.Frequency.WEEKLY:
        return previous_local.isocalendar()[:2] != local_now.isocalendar()[:2]
    return (previous_local.year, previous_local.month) != (
        local_now.year,
        local_now.month,
    )
