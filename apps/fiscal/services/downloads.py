"""Resumable ATF workflow. Persist intent before any non-idempotent request."""

import logging
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from apps.fiscal.atf.client import open_atf_client
from apps.fiscal.atf.correlation import reconcile_result
from apps.fiscal.atf.errors import (
    AtfArtifactError,
    AtfError,
    AtfIdentityMismatch,
    AtfPermissionError,
    AtfSessionExpired,
    AtfSubmissionUncertain,
    AtfTransientError,
)
from apps.fiscal.atf.profiles import document_profile, result_wait_seconds
from apps.fiscal.atf.types import Period, SubmissionEvidence
from apps.fiscal.models import (
    DownloadArchive,
    DownloadAttempt,
    DownloadPart,
    DownloadPolicy,
    DownloadRequest,
    RemoteSubmissionBarrier,
)
from apps.operations.models import AuditLog
from apps.operations.services import open_operation_alert
from apps.organizations.access import accessible_companies
from apps.organizations.models import ClientCompany

from .artifacts import persist_archive, validate_archive
from .documents import index_archive
from .leases import (
    assert_access,
    begin_submission,
    bind_remote_result,
    claim_access,
    company_scope,
    release_access,
    renew_access,
    reserve_mailbox_poll,
)
from .periods import active_request_key, split_period

logger = logging.getLogger(__name__)
TERMINAL_PARTS = {"succeeded", "empty", "failed"}
TERMINAL_REQUESTS = {"succeeded", "partial", "empty", "failed", "cancelled"}


@dataclass(frozen=True)
class AdvanceResult:
    status: str
    next_eta: datetime | None = None


def _alert(part: Any, code: Any) -> None:
    open_operation_alert(
        company_id=part.request.company_id,
        code=code,
        severity="warning",
        title="Download ATF requer atenção",
        message="Consulte os detalhes do pedido para retomar ou revisar o resultado.",
        context={"request_id": str(part.request_id), "part_id": str(part.pk)},
    )


def enqueue_part(part_id: Any, eta: Any = None) -> None:
    from apps.fiscal.tasks import process_download_part

    try:
        process_download_part.apply_async(args=[str(part_id)], eta=eta)
    except Exception:
        part = DownloadPart.objects.select_related("request").get(pk=part_id)
        _alert(part, "atf_queue_unavailable")
        logger.warning("event=atf_dispatch_failed part_id=%s", part_id)


@transaction.atomic
def request_download(
    *,
    company_id: Any,
    period: Any,
    formats: Any,
    actor_id: Any,
    trigger: Any,
    document_model: str = "55",
    repeat_of: Any = None,
    dispatch: Any = True,
) -> DownloadRequest:
    if trigger not in {"manual", "scheduled"} or period.end > timezone.localdate():
        raise ValidationError("Período ou origem inválidos.")
    company = ClientCompany.objects.select_for_update().get(
        pk=company_id, status="active"
    )
    policy = DownloadPolicy.objects.filter(company=company).first()
    if trigger == "manual":
        if actor_id is None:
            raise PermissionDenied()
        actor = get_user_model().objects.get(pk=actor_id)
        if (
            not actor.is_active
            or not accessible_companies(actor).filter(pk=company_id).exists()
        ):
            raise PermissionDenied()
    elif policy is None or not policy.is_active or policy.mode == "manual":
        raise ValidationError("Agendamento inativo.")
    canonical = tuple(sorted(set(formats)))
    key = active_request_key(company_id, period, canonical, document_model)
    active = DownloadRequest.objects.filter(
        active_key=key, status__in=("queued", "running", "waiting")
    ).first()
    if active:
        return active
    previous = (
        DownloadRequest.objects.filter(active_key=key).order_by("-created_at").first()
    )
    if previous and trigger == "manual" and repeat_of != previous.pk:
        raise ValidationError(
            "Período já solicitado. Confirme a repetição do pedido anterior."
        )
    if repeat_of and (previous is None or repeat_of != previous.pk):
        raise ValidationError("Pedido anterior incompatível.")
    request = DownloadRequest.objects.create(
        company=company,
        policy=policy,
        start_date=period.start,
        end_date=period.end,
        formats=list(canonical),
        document_model=document_model,
        active_key=key,
        requested_by_id=actor_id,
        trigger=trigger,
        repeat_of=previous,
        requested_on=timezone.now()
        .astimezone(ZoneInfo(policy.timezone if policy else settings.TIME_ZONE))
        .date(),
    )
    for portion in split_period(period, document_model):
        for format in canonical:
            DownloadPart.objects.create(
                request=request,
                start_date=portion.start,
                end_date=portion.end,
                format=format,
            )
    AuditLog.objects.create(
        actor_id=actor_id,
        action="fiscal.download_requested",
        target=f"download:{request.pk}",
        payload={"trigger": trigger},
    )
    if dispatch:
        first = request.parts.earliest("start_date", "format")
        transaction.on_commit(lambda: enqueue_part(first.pk))
    return request


@transaction.atomic
def consolidate_request(request_id: Any) -> None:
    request = DownloadRequest.objects.select_for_update().get(pk=request_id)
    if request.status == "cancelled":
        return
    states = list(request.parts.values_list("status", flat=True))
    old_status = request.status
    if states and all(state in TERMINAL_PARTS for state in states):
        delivered = DownloadArchive.objects.filter(part__request=request).exists()
        if "failed" in states:
            request.status = "partial" if delivered else "failed"
        else:
            request.status = "succeeded" if delivered else "empty"
        request.finished_at = timezone.now()
    elif any(
        state in {"waiting", "ambiguous", "submitting", "downloading", "validating"}
        for state in states
    ):
        request.status = "waiting"
    else:
        request.status = "running"
    request.save(update_fields=["status", "finished_at"])
    if (
        request.policy_id
        and request.status in TERMINAL_REQUESTS
        and old_status not in TERMINAL_REQUESTS
    ):
        policy = DownloadPolicy.objects.select_for_update().get(pk=request.policy_id)
        policy.last_finished_at = request.finished_at
        policy.last_result = request.status
        policy.failure_count = (
            policy.failure_count + 1 if request.status in {"failed", "partial"} else 0
        )
        policy.save(update_fields=["last_finished_at", "last_result", "failure_count"])


def _all_messages(client: Any, parent_id: Any = None) -> Any:
    refs, cursor, seen = [], None, set()
    for _ in range(getattr(settings, "ATF_MAX_MESSAGE_PAGES", 100)):
        page = client.list_messages(cursor=cursor, parent_id=parent_id)
        refs.extend(page.items)
        if not page.next_page:
            return tuple(refs)
        if page.next_page in seen:
            raise AtfArtifactError("atf_pagination_cycle")
        seen.add(page.next_page)
        cursor = page.next_page
    raise AtfArtifactError("atf_message_page_limit")


def _read_group(client: Any, group: Any, sender_code: str) -> Any:
    if group.children_count:
        refs = _all_messages(client, group.id)
    else:
        refs = (group,)
    if len(refs) > getattr(settings, "ATF_MAX_GROUP_MESSAGES", 200):
        raise AtfArtifactError("atf_group_limit")
    return tuple(
        client.read_message(ref.id, group.id)
        for ref in refs
        if ref.sender_code == sender_code
    )


@transaction.atomic
def _schedule(
    part: Any,
    now: Any,
    dispatch: Any,
    *,
    token: Any,
    status: Any = None,
    eta: Any = None,
) -> AdvanceResult:
    assert_access(token, now=max(now, timezone.now()))
    current = DownloadPart.objects.select_for_update().get(pk=part.pk)
    if current.status in TERMINAL_PARTS:
        part.refresh_from_db()
        return AdvanceResult(current.status)
    delay = max(60, getattr(settings, "ATF_POLL_INTERVAL_SECONDS", 60))
    if part.request.document_model == "65" and part.submitted_at:
        cap = max(delay, getattr(settings, "ATF_NFCE_MAX_POLL_INTERVAL_SECONDS", 900))
        delay = min(cap, delay * 2 ** min(part.poll_count // 3, 8))
    eta = eta or now + timedelta(seconds=delay)
    if status:
        part.status = status
    part.next_poll_at = eta
    part.save(update_fields=["status", "next_poll_at", "error_code"])
    consolidate_request(part.request_id)
    if dispatch:
        transaction.on_commit(lambda: enqueue_part(part.pk, eta))
    return AdvanceResult(part.status, eta)


def _finish(part: Any, token: Any, status: Any, now: Any) -> AdvanceResult:
    with transaction.atomic():
        assert_access(token, now=max(now, timezone.now()))
        current = DownloadPart.objects.select_for_update().get(pk=part.pk)
        current.status = status
        current.error_code = ""
        current.next_poll_at = None
        current.save(update_fields=["status", "error_code", "next_poll_at"])
        RemoteSubmissionBarrier.objects.filter(part=current).delete()
    part.status = status
    consolidate_request(part.request_id)
    return AdvanceResult(status)


@transaction.atomic
def _defer_scheduled_retry(
    part: Any, now: Any, dispatch: Any, *, token: Any, retry_after: Any = 0
) -> AdvanceResult | None:
    """Keep the same period and remote intent across extended SEFAZ outages."""
    assert_access(token, now=max(now, timezone.now()))
    if (
        part.request.trigger != "scheduled"
        or not DownloadPolicy.objects.filter(
            pk=part.request.policy_id,
            is_active=True,
            mode__in=["automatic", "hybrid"],
            company__status="active",
        ).exists()
    ):
        return None
    base = max(1800, int(getattr(settings, "ATF_RETRY_CYCLE_SECONDS", 1800)))
    delay = max(
        min(base * 2 ** min(part.retry_cycle, 6), 86400), min(retry_after, 604800)
    )
    part.retry_count = 0
    part.retry_cycle += 1
    if part.submitted_at:
        part.deadline_at = now + timedelta(
            seconds=delay + result_wait_seconds(part.request.document_model)
        )
    part.save(update_fields=["retry_count", "retry_cycle", "deadline_at"])
    return _schedule(
        part, now, dispatch, eta=now + timedelta(seconds=delay), token=token
    )


def _deliver(
    part: Any, token: Any, client: Any, messages: Any, now: Any
) -> AdvanceResult:
    expected = Period(part.start_date, part.end_date)
    matched = [
        message
        for message in messages
        if message.period == expected and message.outcome == "success"
    ]
    if not matched or not any(message.attachments for message in matched):
        raise AtfArtifactError("atf_missing_attachment")
    DownloadPart.objects.filter(pk=part.pk).update(status="downloading")
    for message in matched:
        # Reopen immediately before reading each attachment. The index is session-local.
        for ref in message.attachments:
            with transaction.atomic():
                assert_access(token, now=max(now, timezone.now()))
            client.read_message(ref.message_id, part.remote_parent_id)
            existing = part.archives.filter(
                message_id=ref.message_id, attachment_index=ref.index
            ).first()
            if existing:
                index_archive(
                    existing.pk, heartbeat=getattr(client, "keep_alive", None)
                )
                continue
            download = client.download_attachment(ref)
            try:
                validation = validate_archive(
                    download,
                    company_id=part.request.company_id,
                    period=expected,
                    format=part.format,
                    document_model=part.request.document_model,
                    heartbeat=getattr(client, "keep_alive", None),
                )
                with transaction.atomic():
                    assert_access(token, now=max(now, timezone.now()))
                    archive = persist_archive(part.pk, ref, download, validation)
                index_archive(archive.pk, heartbeat=getattr(client, "keep_alive", None))
            finally:
                download.staging_path.unlink(missing_ok=True)
    return _finish(part, token, "succeeded", now)


def advance_part(
    part_id: Any, *, client_factory: Any = None, now: Any = None, dispatch: Any = True
) -> AdvanceResult:
    now = now or timezone.now()
    default_client = client_factory is None
    part = DownloadPart.objects.select_related("request__company").get(pk=part_id)
    if part.status in TERMINAL_PARTS or part.request.status == "cancelled":
        return AdvanceResult(part.status)
    if part.next_poll_at and part.next_poll_at > now:
        return AdvanceResult(part.status, part.next_poll_at)
    company_token = claim_access(
        company_scope(part.request.company.tax_identifier), part.pk, now=now
    )
    if company_token is None:
        part.refresh_from_db()
        return AdvanceResult(part.status, part.next_poll_at)
    sender_code = document_profile(part.request.document_model).sender_code
    account_token = None
    attempt = DownloadAttempt.objects.create(part=part, operation="connect")
    elapsed_start = time.monotonic()

    def current_time() -> Any:
        return max(
            timezone.now(), now + timedelta(seconds=time.monotonic() - elapsed_start)
        )

    def heartbeat() -> Any:
        current = current_time()
        renew_access(company_token, now=current)
        if account_token:
            renew_access(account_token, now=current)

    try:
        part = DownloadPart.objects.select_related("request__company").get(pk=part_id)
        if part.status in TERMINAL_PARTS or part.request.status == "cancelled":
            return AdvanceResult(part.status)
        if part.request.company.status != "active":
            part.status = "failed"
            part.error_code = "atf_company_inactive"
            part.save(update_fields=["status", "error_code"])
            consolidate_request(part.request_id)
            return AdvanceResult("failed")
        if (
            part.request.trigger == "scheduled"
            and not DownloadPolicy.objects.filter(
                pk=part.request.policy_id or 0,
                is_active=True,
                mode__in=["automatic", "hybrid"],
            ).exists()
        ):
            part.error_code = "atf_schedule_inactive"
            part.status = "failed"
            part.save(update_fields=["status", "error_code"])
            consolidate_request(part.request_id)
            return AdvanceResult("failed")
        context = (
            open_atf_client(
                part.request.company_id,
                heartbeat=heartbeat,
                account_key_hint=part.remote_account_key or None,
            )
            if default_client
            else client_factory(part.request.company_id)
        )
        with context as client:
            account = client.identity.account_key
            if part.remote_account_key and part.remote_account_key != account:
                raise AtfIdentityMismatch("atf_remote_identity_changed")
            account_token = claim_access(
                "account:" + account, part.pk, now=current_time()
            )
            if account_token is None:
                return _schedule(part, now, dispatch, token=company_token)
            part.remote_account_key = account
            part.save(update_fields=["remote_account_key"])
            client.heartbeat = heartbeat
            retry_at = reserve_mailbox_poll(account_token, now=current_time())
            if retry_at:
                return _schedule(part, now, dispatch, eta=retry_at, token=company_token)
            if part.status == "queued":
                scopes = [company_token.scope, account_token.scope]
                if (
                    RemoteSubmissionBarrier.objects.filter(scope__in=scopes)
                    .exclude(part=part)
                    .exists()
                ):
                    return _schedule(part, now, dispatch, token=company_token)
                issuer = client.lookup_issuer(
                    part.request.company.tax_identifier,
                    document_model=part.request.document_model,
                )
                baseline = tuple(
                    ref.id
                    for ref in _all_messages(client)
                    if ref.sender_code == sender_code
                )
                attempt.operation = "submit"
                attempt.save(update_fields=["operation"])
                evidence = SubmissionEvidence(part.pk, attempt.pk, baseline, now)
                begin_submission(part.pk, account_token, evidence, now=current_time())
                part.refresh_from_db()
                try:
                    receipt = client.submit_query(
                        issuer,
                        Period(part.start_date, part.end_date),
                        part.format,
                        document_model=part.request.document_model,
                    )
                    if not receipt.accepted:
                        raise AtfSubmissionUncertain()
                except AtfError:
                    attempt.submission_certainty = "uncertain"
                    attempt.save(update_fields=["submission_certainty"])
                    raise
                with transaction.atomic():
                    assert_access(account_token, now=current_time())
                    attempt.submission_certainty = "accepted"
                    attempt.outcome = "accepted"
                    attempt.finished_at = current_time()
                    attempt.save()
                return _schedule(
                    part, now, dispatch, status="waiting", token=company_token
                )
            attempt.operation = "poll"
            attempt.save(update_fields=["operation"])
            if part.deadline_at and now > part.deadline_at:
                part.error_code = "atf_wait_timeout"
                deferred = _defer_scheduled_retry(
                    part, now, dispatch, token=company_token
                )
                if deferred:
                    return deferred
                part.status = "failed"
                part.save(update_fields=["status", "error_code"])
                _alert(part, "atf_wait_timeout")
                consolidate_request(part.request_id)
                return AdvanceResult("failed")
            roots = _all_messages(client)
            relevant = [
                ref
                for ref in roots
                if ref.sender_code == sender_code
                and (
                    ref.id == part.remote_parent_id
                    if part.remote_parent_id
                    else ref.id not in part.baseline_ids
                )
            ]
            if len(relevant) > getattr(settings, "ATF_MAX_CANDIDATE_GROUPS", 50):
                raise AtfArtifactError("atf_candidate_limit")
            messages = tuple(
                message
                for group in relevant
                for message in _read_group(client, group, sender_code)
            )
            evidence = SubmissionEvidence(
                part.pk, attempt.pk, tuple(part.baseline_ids), part.submitted_at or now
            )
            result = reconcile_result(
                evidence,
                messages,
                period=Period(part.start_date, part.end_date),
                document_model=part.request.document_model,
            )
            part.candidates = list(result.candidates)
            part.save(update_fields=["candidates"])
            if result.outcome == "matched":
                bind_remote_result(
                    part.pk, account, result.candidates[0], actor_id=None
                )
                part.refresh_from_db()
                return _deliver(
                    part,
                    account_token,
                    client,
                    tuple(
                        item
                        for item in messages
                        if (item.ref.parent_id or item.ref.id) == part.remote_parent_id
                    ),
                    now,
                )
            if result.outcome in {"empty", "remote_failed"}:
                proven = [
                    message
                    for message in messages
                    if message.filters.get("issuer_cnpj")
                    == part.request.company.tax_identifier
                    and message.filters.get("format") == part.format
                    and message.period == result.confirmed_period
                ]
                if proven:
                    return _finish(
                        part,
                        account_token,
                        "empty" if result.outcome == "empty" else "failed",
                        now,
                    )
                result_status = "ambiguous"
            else:
                result_status = (
                    "ambiguous" if result.outcome == "ambiguous" else "waiting"
                )
            part.poll_count += 1
            part.save(update_fields=["poll_count"])
            if result_status == "ambiguous":
                _alert(part, "atf_result_ambiguous")
            return _schedule(
                part, now, dispatch, status=result_status, token=company_token
            )
    except AtfPermissionError as error:
        if error.args == ("atf_lease_lost",):
            return AdvanceResult(part.status)
        part.error_code = error.safe_code
        _alert(part, error.safe_code)
        part.status = "failed"
        part.save(update_fields=["status", "error_code"])
        consolidate_request(part.request_id)
        return AdvanceResult("failed")
    except AtfError as error:
        if account_token:
            with transaction.atomic():
                assert_access(account_token, now=current_time())
        part.refresh_from_db()
        part.error_code = error.safe_code
        _alert(part, error.safe_code)
        if isinstance(error, AtfSubmissionUncertain):
            return _schedule(
                part, now, dispatch, status="ambiguous", token=company_token
            )
        if isinstance(error, (AtfTransientError, AtfSessionExpired)):
            retry_after = min(max(0, getattr(error, "retry_after_seconds", 0)), 604800)
            if part.retry_count < 3:
                part.retry_count += 1
                part.save(update_fields=["retry_count"])
                delay = max(60 * 2 ** (part.retry_count - 1), retry_after)
                return _schedule(
                    part,
                    current_time(),
                    dispatch,
                    eta=current_time() + timedelta(seconds=delay),
                    token=company_token,
                )
            deferred = _defer_scheduled_retry(
                part,
                current_time(),
                dispatch,
                retry_after=retry_after,
                token=company_token,
            )
            if deferred:
                return deferred
        part.status = "failed"
        part.save(update_fields=["status", "error_code"])
        consolidate_request(part.request_id)
        return AdvanceResult("failed")
    finally:
        if attempt and attempt.finished_at is None:
            DownloadAttempt.objects.filter(pk=attempt.pk).update(
                finished_at=current_time(),
                outcome=part.status,
                error_code=part.error_code,
            )
        if account_token:
            release_access(account_token)
        release_access(company_token)
        if (
            dispatch
            and part.status in TERMINAL_PARTS
            and not RemoteSubmissionBarrier.objects.filter(part=part).exists()
        ):
            sibling = part.request.parts.filter(status="queued").first()
            if sibling:
                transaction.on_commit(lambda: enqueue_part(sibling.pk))
