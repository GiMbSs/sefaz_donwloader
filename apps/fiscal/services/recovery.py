"""Deliberate recovery after stopping a worker with an uncertain request."""

from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from apps.fiscal.models import DistributionBatch, NsuControl, SyncRequest
from apps.fiscal.services.execution import (
    _finish_failed,
    _finish_succeeded,
)
from apps.operations.models import AuditLog
from apps.organizations.access import manageable_companies
from apps.organizations.models import ClientCompany


class SynchronizationRecoveryError(ValueError):
    pass


def recover_interrupted_request(
    *, request_id, actor, reason, worker_stopped=False, now=None
):
    """Never retries I/O; requires the old worker to have been stopped first."""
    now = now or timezone.now()
    reason = reason.strip()
    if not worker_stopped:
        raise SynchronizationRecoveryError("Confirme que o worker foi interrompido.")
    if not reason or len(reason) > 500:
        raise SynchronizationRecoveryError("Informe um motivo de até 500 caracteres.")
    with transaction.atomic():
        candidate = SyncRequest.objects.filter(pk=request_id).first()
        if candidate is None:
            raise SynchronizationRecoveryError("Solicitação não encontrada.")
        company = (
            ClientCompany.objects.select_for_update()
            .filter(
                pk=candidate.company_id,
                pk__in=manageable_companies(actor).values("pk"),
            )
            .first()
        )
        if company is None:
            raise SynchronizationRecoveryError("Sem autorização para esta empresa.")
        request = SyncRequest.objects.select_for_update().get(pk=request_id)
        if request.status != SyncRequest.Status.RUNNING:
            raise SynchronizationRecoveryError("A solicitação não está em execução.")
        if request.started_at is None or request.started_at > now - timedelta(hours=1):
            raise SynchronizationRecoveryError(
                "A recuperação exige uma solicitação iniciada há pelo menos uma hora."
            )
        NsuControl.objects.select_for_update().get(
            company=company, environment=request.environment, service="nfe_distribution"
        )
        batch = (
            DistributionBatch.objects.filter(
                sync_request=request, processing_status="processed"
            )
            .order_by("-processed_at", "-pk")
            .first()
        )
        if batch is not None:
            _finish_succeeded(sync_request_id=request.pk, batch=batch, now=now)
        else:
            _finish_failed(
                sync_request_id=request.pk,
                now=now,
                detail=(
                    "Pedido interrompido encerrado por administrador. "
                    "A comunicação anterior é incerta; aguarde a janela fiscal "
                    "e revise os lotes antes de solicitar novamente."
                ),
                reason="interrupted_request",
                hold_cursor=True,
            )
        request.refresh_from_db()
        AuditLog.objects.create(
            actor=actor,
            action="fiscal.interrupted_request_recovered",
            target=f"fiscal.sync_request:{request.pk}",
            payload={
                "company_id": company.pk,
                "environment": request.environment,
                "status": request.status,
                "reason": reason,
                "worker_stopped_confirmed": True,
            },
        )
        return request
