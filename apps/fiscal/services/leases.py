"""Database leases fence local work; persistent barriers fence uncertain POSTs."""

import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID, uuid4

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.utils import timezone

from apps.fiscal.atf.errors import (
    AtfAmbiguousResult,
    AtfPermissionError,
    AtfSubmissionUncertain,
)
from apps.fiscal.atf.profiles import result_wait_seconds
from apps.fiscal.atf.types import SubmissionEvidence
from apps.fiscal.models import (
    AtfAccessLease,
    DownloadPart,
    DownloadRequest,
    RemoteResultBinding,
    RemoteSubmissionBarrier,
)
from apps.operations.models import AuditLog
from apps.organizations.access import manageable_companies


@dataclass(frozen=True)
class LeaseToken:
    scope: str
    owner: UUID
    generation: int
    expires_at: datetime


def company_scope(cnpj: str) -> str:
    return "company:" + hashlib.sha256(cnpj.encode()).hexdigest()


@transaction.atomic
def claim_access(scope: str, part_id: UUID, *, now: datetime) -> LeaseToken | None:
    AtfAccessLease.objects.get_or_create(scope=scope, defaults={"expires_at": now})
    lease = AtfAccessLease.objects.select_for_update().get(scope=scope)
    if lease.expires_at > now:
        return None
    lease.owner = uuid4()
    lease.generation += 1
    lease.part_id = part_id
    lease.expires_at = now + timedelta(
        seconds=getattr(settings, "ATF_ACCESS_LEASE_SECONDS", 300)
    )
    lease.save()
    return LeaseToken(scope, lease.owner, lease.generation, lease.expires_at)


def assert_access(token: LeaseToken, *, now: datetime) -> AtfAccessLease:
    lease = (
        AtfAccessLease.objects.select_for_update()
        .filter(
            scope=token.scope,
            owner=token.owner,
            generation=token.generation,
            expires_at__gt=now,
        )
        .first()
    )
    if lease is None:
        raise AtfPermissionError("atf_lease_lost")
    if lease.part_id:
        part = DownloadPart.objects.get(pk=lease.part_id)
        assert_part_active(part)
    return lease


def assert_part_active(part: DownloadPart) -> None:
    if (
        part.status == "cancelled"
        or DownloadRequest.objects.filter(
            pk=part.request_id, status="cancelled"
        ).exists()
    ):
        raise AtfPermissionError("atf_lease_lost")


@transaction.atomic
def renew_access(token: LeaseToken, *, now: datetime) -> LeaseToken:
    lease = assert_access(token, now=now)
    lease.expires_at = now + timedelta(
        seconds=getattr(settings, "ATF_ACCESS_LEASE_SECONDS", 300)
    )
    lease.save(update_fields=["expires_at"])
    return LeaseToken(lease.scope, lease.owner, lease.generation, lease.expires_at)


@transaction.atomic
def release_access(token: LeaseToken) -> None:
    AtfAccessLease.objects.filter(
        scope=token.scope, owner=token.owner, generation=token.generation
    ).update(expires_at=timezone.now())


@transaction.atomic
def reserve_mailbox_poll(token: LeaseToken, *, now: datetime) -> datetime | None:
    lease = assert_access(token, now=now)
    if lease.next_poll_at and lease.next_poll_at > now:
        return lease.next_poll_at
    lease.next_poll_at = now + timedelta(
        seconds=max(60, getattr(settings, "ATF_POLL_INTERVAL_SECONDS", 60))
    )
    lease.save(update_fields=["next_poll_at"])
    return None


@transaction.atomic
def begin_submission(
    part_id: UUID, token: LeaseToken, evidence: SubmissionEvidence, *, now: datetime
) -> None:
    lease = assert_access(token, now=now)
    part = (
        DownloadPart.objects.select_for_update(of=("self",))
        .select_related("request__company")
        .get(pk=part_id)
    )
    assert_part_active(part)
    scopes = sorted(
        [
            company_scope(part.request.company.tax_identifier),
            "account:" + part.remote_account_key,
        ]
    )
    if lease.part_id != part_id or token.scope != "account:" + part.remote_account_key:
        raise AtfPermissionError()
    company_lease = (
        AtfAccessLease.objects.select_for_update()
        .filter(
            scope=scopes[1] if scopes[0].startswith("account:") else scopes[0],
            part_id=part_id,
            expires_at__gt=now,
        )
        .first()
    )
    if company_lease is None or evidence.part_id != part_id:
        raise AtfPermissionError()
    if RemoteSubmissionBarrier.objects.filter(scope__in=scopes).exists():
        raise AtfSubmissionUncertain()
    if part.status != "queued":
        raise AtfSubmissionUncertain()
    for scope in scopes:
        RemoteSubmissionBarrier.objects.create(
            scope=scope, part=part, attempt_id=evidence.attempt_id
        )
    part.status = "submitting"
    part.baseline_ids = list(evidence.baseline_ids)
    part.submitted_at = evidence.submitted_at
    part.deadline_at = now + timedelta(
        seconds=result_wait_seconds(part.request.document_model)
    )
    part.step_version += 1
    part.save()


@transaction.atomic
def bind_remote_result(
    part_id: UUID, account_key: str, parent_id: str, *, actor_id: int | None
) -> RemoteResultBinding:
    part = (
        DownloadPart.objects.select_for_update(of=("self",))
        .select_related("request")
        .get(pk=part_id)
    )
    assert_part_active(part)
    if part.remote_account_key != account_key or parent_id not in part.candidates:
        raise AtfPermissionError()
    if actor_id is not None:
        user = get_user_model().objects.get(pk=actor_id)
        if (
            not user.is_active
            or not manageable_companies(user)
            .filter(pk=part.request.company_id)
            .exists()
        ):
            raise PermissionDenied()
    binding, _ = RemoteResultBinding.objects.get_or_create(
        remote_account_key=account_key,
        parent_message_id=parent_id,
        defaults={"part": part, "confirmed_by_id": actor_id},
    )
    if binding.part_id != part_id:
        raise AtfAmbiguousResult()
    part.remote_parent_id = parent_id
    part.save(update_fields=["remote_parent_id"])
    AuditLog.objects.create(
        actor_id=actor_id,
        action="fiscal.atf_result_bound",
        target=f"part:{part.pk}",
        payload={"manual": actor_id is not None},
    )
    return binding
