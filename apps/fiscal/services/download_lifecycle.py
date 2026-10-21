"""Administrative local cancellation and removal from operational screens."""

from typing import Any

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from apps.fiscal.models import (
    DownloadAttempt,
    DownloadPart,
    DownloadRequest,
    RemoteSubmissionBarrier,
)
from apps.operations.models import AuditLog
from apps.organizations.access import manageable_companies
from apps.organizations.models import ClientCompany

from .download_deletion import (
    dispatch_file_deletion,
    lock_company_parts,
    prepare_file_deletion,
)


def _authorized_request(request_id: Any, actor_id: Any) -> DownloadRequest:
    actor = get_user_model().objects.get(pk=actor_id)
    request = DownloadRequest.objects.get(pk=request_id)
    if (
        not actor.is_active
        or not manageable_companies(actor).filter(pk=request.company_id).exists()
    ):
        raise PermissionDenied()
    return request


def _reason(note: str) -> str:
    note = note.strip()
    if not note or len(note) > 2000:
        raise ValidationError("Informe um motivo de até 2000 caracteres.")
    return note


@transaction.atomic
def cancel_download_request(
    request_id: Any,
    *,
    actor_id: Any,
    note: str,
    acknowledge_remote_uncertainty: bool,
) -> DownloadRequest:
    request = _authorized_request(request_id, actor_id)
    note = _reason(note)
    if not acknowledge_remote_uncertainty:
        raise ValidationError("Confirme o encerramento local do pedido.")
    ClientCompany.objects.select_for_update(no_key=True).get(pk=request.company_id)
    request = _authorized_request(request_id, actor_id)
    # Same part -> request lock order as recovery and worker consolidation.
    parts = list(
        DownloadPart.objects.select_for_update()
        .filter(request_id=request_id)
        .order_by("pk")
    )
    request = DownloadRequest.objects.select_for_update().get(pk=request_id)
    if request.deleted_at:
        raise ValidationError("Este pedido já foi excluído da operação.")
    if request.status == "cancelled":
        return request
    if request.status in {"succeeded", "empty"}:
        raise ValidationError("Este pedido já foi concluído.")
    now = timezone.now()
    pending = [part.pk for part in parts if part.status not in {"succeeded", "empty"}]
    remote_pending = any(part.submitted_at for part in parts)
    DownloadPart.objects.filter(pk__in=pending).update(
        status="cancelled",
        next_poll_at=None,
        error_code="",
        step_version=F("step_version") + 1,
    )
    DownloadAttempt.objects.filter(
        part_id__in=pending, finished_at__isnull=True
    ).update(finished_at=now, outcome="cancelled")
    RemoteSubmissionBarrier.objects.filter(part__request_id=request_id).delete()
    request.status = "cancelled"
    request.finished_at = now
    request.result_detail = note
    request.save(update_fields=["status", "finished_at", "result_detail"])
    AuditLog.objects.create(
        actor_id=actor_id,
        action="fiscal.download_cancelled",
        target=f"download:{request.pk}",
        payload={
            "note": note,
            "parts": len(pending),
            "remote_may_exist": remote_pending,
        },
    )
    return request


@transaction.atomic
def delete_cancelled_download_request(
    request_id: Any, *, actor_id: Any, note: str, dispatch: bool = True
) -> DownloadRequest:
    request = _authorized_request(request_id, actor_id)
    note = _reason(note)
    lock_company_parts(request.company_id)
    request = _authorized_request(request_id, actor_id)
    request = DownloadRequest.objects.select_for_update().get(pk=request_id)
    if request.status != "cancelled":
        raise ValidationError("Cancele o pedido antes de excluí-lo.")
    if request.deleted_at:
        return request
    file_count = prepare_file_deletion(request)
    request.deleted_at = timezone.now()
    request.save(update_fields=["deleted_at"])
    AuditLog.objects.create(
        actor_id=actor_id,
        action="fiscal.download_deleted",
        target=f"download:{request.pk}",
        payload={"note": note, "files_requested_for_deletion": file_count},
    )
    if dispatch and file_count:
        transaction.on_commit(lambda: dispatch_file_deletion(request.pk))
    return request
