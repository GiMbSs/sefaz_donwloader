from dataclasses import dataclass
from datetime import timedelta
from functools import partial
from typing import Any
from uuid import UUID

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from apps.fiscal.atf.profiles import result_wait_seconds
from apps.fiscal.models import (
    AtfAccessLease,
    DownloadPart,
    DownloadRequest,
    RemoteSubmissionBarrier,
)
from apps.operations.models import AuditLog
from apps.organizations.access import accessible_companies, manageable_companies
from apps.organizations.models import ClientCompany

from .downloads import consolidate_request, enqueue_part


@dataclass(frozen=True)
class RecoveryResult:
    resumed_parts: tuple[UUID, ...]
    requires_review: bool = False


@transaction.atomic
def recover_download_request(
    request_id: Any, *, actor_id: Any, note: Any, dispatch: Any = True
) -> Any:
    company_id = DownloadRequest.objects.values_list("company_id", flat=True).get(
        pk=request_id
    )
    # Match request_download's company lock so a repeat cannot be created
    # between the active-key check and reactivation of this request.
    ClientCompany.objects.select_for_update().get(pk=company_id)
    # Workers lock a part before consolidating its request. Lock every part
    # first, in a stable order, so recovery never holds the request while
    # waiting for a worker's part lock. Re-read states after obtaining locks.
    parts = list(
        DownloadPart.objects.select_for_update()
        .filter(request_id=request_id)
        .order_by("pk")
    )
    request = DownloadRequest.objects.select_for_update().get(pk=request_id)
    user = get_user_model().objects.get(pk=actor_id)
    if (
        not user.is_active
        or not accessible_companies(user).filter(pk=request.company_id).exists()
    ):
        raise PermissionDenied()
    if not note.strip():
        raise ValidationError("Registre o motivo da retomada.")
    if request.status == "cancelled":
        raise ValidationError(
            "Pedido cancelado localmente; crie um novo pedido explícito."
        )
    if (
        DownloadRequest.objects.filter(
            active_key=request.active_key, status__in=["queued", "running", "waiting"]
        )
        .exclude(pk=request.pk)
        .exists()
    ):
        raise ValidationError(
            "Já existe um pedido equivalente ativo. Retome esse pedido."
        )
    now, resumed, review = timezone.now(), [], False
    for part in parts:
        if part.status in {"succeeded", "empty"}:
            continue
        if AtfAccessLease.objects.filter(part=part, expires_at__gt=now).exists():
            raise ValidationError("Aguarde a etapa em execução terminar.")
        uncertain = (
            part.submitted_at is not None
            or RemoteSubmissionBarrier.objects.filter(part=part).exists()
        )
        if len(part.candidates) > 1 and not part.remote_parent_id:
            review = True
            continue
        if uncertain:
            part.status = "waiting"
            part.deadline_at = now + timedelta(
                seconds=result_wait_seconds(request.document_model)
            )
        else:
            part.status = "queued"
        part.next_poll_at = now
        part.retry_count = 0
        part.error_code = ""
        part.save()
        resumed.append(part.pk)
        if dispatch:
            transaction.on_commit(partial(enqueue_part, part.pk))
    AuditLog.objects.create(
        actor=user,
        action="fiscal.download_recovered",
        target=f"download:{request.pk}",
        payload={"note": note[:2000], "parts": len(resumed)},
    )
    consolidate_request(request.pk)
    return RecoveryResult(tuple(resumed), review)


@transaction.atomic
def abandon_uncertain_submission(
    part_id: Any, *, actor_id: Any, note: Any, acknowledge_remote_uncertainty: Any
) -> Any:
    part = (
        DownloadPart.objects.select_for_update(of=("self",))
        .select_related("request")
        .get(pk=part_id)
    )
    user = get_user_model().objects.get(pk=actor_id)
    if (
        not user.is_active
        or not manageable_companies(user).filter(pk=part.request.company_id).exists()
    ):
        raise PermissionDenied()
    if not acknowledge_remote_uncertainty or not note.strip():
        raise ValidationError(
            "Confirme que o pedido ainda pode existir no ATF e registre o motivo."
        )
    if AtfAccessLease.objects.filter(part=part, expires_at__gt=timezone.now()).exists():
        raise ValidationError("Há uma etapa em execução.")
    part.status = "failed"
    part.error_code = "atf_uncertain_submission_abandoned"
    part.next_poll_at = None
    part.save()
    RemoteSubmissionBarrier.objects.filter(part=part).delete()
    AuditLog.objects.create(
        actor=user,
        action="fiscal.uncertain_submission_abandoned",
        target=f"part:{part.pk}",
        payload={"note": note[:2000], "remote_may_exist": True},
    )
    consolidate_request(part.request_id)
