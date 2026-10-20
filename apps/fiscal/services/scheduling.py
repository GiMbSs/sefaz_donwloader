"""Preserve programmable schedules while deriving explicit ATF periods."""

import calendar
from datetime import date, datetime, time, timedelta
from functools import partial
from zoneinfo import ZoneInfo

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q

from apps.fiscal.atf.types import Period
from apps.fiscal.models import DownloadPart, DownloadPolicy
from apps.operations.services import open_operation_alert
from apps.organizations.models import ClientCompany

from .downloads import enqueue_part, request_download


def period_for_policy(policy: DownloadPolicy, now: datetime) -> Period:
    if now.tzinfo is None:
        raise ValidationError("Informe horário com fuso.")
    today = now.astimezone(ZoneInfo(policy.timezone)).date()
    end = today - timedelta(days=1)
    if policy.period_strategy == "previous_day":
        start = end
    elif policy.period_strategy == "previous_month":
        end = today.replace(day=1) - timedelta(days=1)
        start = end.replace(day=1)
    elif policy.period_strategy == "rolling_days" and policy.rolling_days >= 1:
        start = end - timedelta(days=policy.rolling_days - 1)
    else:
        raise ValidationError("Estratégia de período inválida.")
    return Period(start, end)


def _slot(policy: DownloadPolicy, now: datetime) -> str | None:
    local = now.astimezone(ZoneInfo(policy.timezone))
    if policy.mode == "manual" or not policy.is_active or policy.scheduled_time is None:
        return None
    if local.time() < policy.scheduled_time:
        return None
    if policy.frequency == "weekly" and local.weekday() not in policy.weekdays:
        return None
    if policy.frequency == "monthly" and local.day != min(
        policy.monthday, calendar.monthrange(local.year, local.month)[1]
    ):
        return None
    return local.date().isoformat() + "/" + str(policy.frequency)


def _due_occurrences(policy: DownloadPolicy, now: datetime) -> list[datetime]:
    zone = ZoneInfo(policy.timezone)
    local = now.astimezone(zone)
    first = local.date()
    if policy.last_scheduled_slot:
        raw_date, _, frequency = policy.last_scheduled_slot.partition("/")
        if frequency == policy.frequency:
            first = date.fromisoformat(raw_date) + timedelta(days=1)
    occurrences = []
    for offset in range(366):
        day = first + timedelta(days=offset)
        if day > local.date():
            break
        occurrence = (
            local if day == local.date() else datetime.combine(day, time.max, zone)
        )
        if _slot(policy, occurrence):
            occurrences.append(occurrence)
    return occurrences


def enqueue_due_downloads(*, now: datetime, dispatch: bool = True) -> int:
    if not getattr(settings, "ATF_PB_ENABLED", False):
        return 0
    queued = 0
    policies = DownloadPolicy.objects.filter(
        is_active=True, company__status="active"
    ).exclude(mode="manual")
    for pk, company_id in policies.values_list("pk", "company_id"):
        with transaction.atomic():
            ClientCompany.objects.select_for_update().get(pk=company_id)
            policy = DownloadPolicy.objects.select_for_update().get(pk=pk)
            try:
                policy.full_clean()
                occurrences = _due_occurrences(policy, now)
                for occurrence in occurrences:
                    for document_model in dict.fromkeys(policy.document_models):
                        request = request_download(
                            company_id=policy.company_id,
                            period=period_for_policy(policy, occurrence),
                            formats=tuple(policy.formats),
                            document_model=document_model,
                            actor_id=None,
                            trigger="scheduled",
                            dispatch=False,
                        )
                        if dispatch:
                            first = request.parts.earliest("start_date", "format")
                            transaction.on_commit(partial(enqueue_part, first.pk))
                        queued += 1
                    policy.last_scheduled_slot = _slot(policy, occurrence) or ""
                    policy.last_requested_at = now
                    policy.save(
                        update_fields=["last_scheduled_slot", "last_requested_at"]
                    )
            except (ValidationError, ValueError):
                open_operation_alert(
                    company_id=policy.company_id,
                    code="atf_schedule_invalid",
                    severity="warning",
                    title="Revise o agendamento",
                    message="A configuração do agendamento precisa de ajuste.",
                )
    if dispatch:
        due = (
            DownloadPart.objects.filter(
                request__status__in=["queued", "running", "waiting"],
                request__company__status="active",
            )
            .exclude(status__in=["succeeded", "empty", "failed"])
            .filter(
                Q(next_poll_at__lte=now)
                | Q(
                    next_poll_at__isnull=True,
                    request__created_at__lte=now - timedelta(minutes=5),
                )
            )
            .order_by("request__created_at")[:100]
        )
        for part in due:
            enqueue_part(part.pk)
    return queued
