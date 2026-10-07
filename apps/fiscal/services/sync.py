"""Use cases for creating safe, idempotent DF-e synchronization requests."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
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
        return SyncRequestSubmission(request=request, created=True)


def enqueue_due_synchronizations(*, now: datetime | None = None) -> int:
    """Queue due daily policies once, regardless of Beat's polling cadence."""
    now = now or timezone.now()
    due_policies = SyncPolicy.objects.select_related("company").filter(
        is_active=True,
        company__status=ClientCompany.Status.ACTIVE,
        mode__in=(SyncPolicy.Mode.DAILY, SyncPolicy.Mode.HYBRID),
    )
    queued = 0
    for policy in due_policies.iterator():
        if not _is_due(policy, now):
            continue
        submission = request_synchronization(
            company_id=policy.company_id,
            environment=NsuControl.Environment.PRODUCTION,
            trigger=SyncRequest.Trigger.SCHEDULED,
            now=now,
        )
        queued += int(submission.created)
    return queued


def _ensure_trigger_allowed(policy: SyncPolicy, trigger: str) -> None:
    if trigger == SyncRequest.Trigger.MANUAL and policy.mode == SyncPolicy.Mode.DAILY:
        raise SynchronizationRequestError(
            "A política atual permite somente sincronização diária."
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
    if policy.weekdays and local_now.weekday() not in policy.weekdays:
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
    return policy.last_requested_at.astimezone(policy_timezone).date() != local_now.date()
