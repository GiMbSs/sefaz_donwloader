"""Worker-side execution for one previously accepted synchronization request.

This module is the only layer that joins a queued request to the SEFAZ client.
It claims database state before network I/O, keeps the I/O outside a database
transaction, and never retries an uncertain remote consultation automatically.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from django.db import transaction
from django.utils import timezone

from apps.certificates.models import DigitalCertificate
from apps.fiscal.models import DistributionBatch, NsuControl, SyncPolicy, SyncRequest
from apps.fiscal.services.distribution import (
    DistributionParseError,
    persist_distribution_response,
)
from apps.fiscal.services.sefaz import (
    NfeDistributionClient,
    SefazDistributionError,
    SefazTransportError,
)
from apps.fiscal.services.storage import FiscalStorage, FiscalStorageError
from apps.operations.models import AuditLog
from apps.operations.services import open_operation_alert


@dataclass(frozen=True)
class ClaimedSynchronization:
    """The minimal immutable state needed after the transaction is released."""

    request_id: int
    company_id: int
    tax_identifier: str
    environment: str
    control_id: int
    last_nsu: str
    certificate: DigitalCertificate


def execute_sync_request(
    sync_request_id: int,
    *,
    client: NfeDistributionClient | None = None,
    storage: FiscalStorage | None = None,
    now: datetime | None = None,
) -> str:
    """Run one request from the fiscal worker and return its final state.

    A task redelivery can encounter a request already running or completed; it
    then only reports the stored state.  A transport or persistence failure is
    terminal for this request and puts the cursor into a conservative one-hour
    hold.  Repeating a ``distNSU`` after an uncertain response can trigger
    SEFAZ consumption limits, so an operator must deliberately create the next
    request after reviewing the failure.
    """
    now = now or timezone.now()
    claimed = _claim_sync_request(sync_request_id=sync_request_id, now=now)
    if isinstance(claimed, str):
        if claimed == SyncRequest.Status.RUNNING:
            batch = (
                DistributionBatch.objects.filter(
                    sync_request_id=sync_request_id,
                    processing_status=DistributionBatch.ProcessingStatus.PROCESSED,
                )
                .order_by("-processed_at", "-pk")
                .first()
            )
            if batch is not None:
                _finish_succeeded(
                    sync_request_id=sync_request_id,
                    batch=batch,
                    now=now,
                )
                return SyncRequest.Status.SUCCEEDED
        return claimed

    client = client or NfeDistributionClient()
    try:
        result = client.request_dist_nsu(
            tax_identifier=claimed.tax_identifier,
            environment=claimed.environment,
            last_nsu=claimed.last_nsu,
            certificate=claimed.certificate,
        )
        batch = persist_distribution_response(
            control_id=claimed.control_id,
            raw_response=result.distribution_response,
            soap_response=result.soap_response,
            sync_request_id=claimed.request_id,
            storage=storage,
        )
    except SefazTransportError:
        _finish_failed(
            sync_request_id=claimed.request_id,
            now=now,
            detail=(
                "A comunicação com a SEFAZ não pôde ser confirmada. "
                "Aguarde uma hora antes de uma nova solicitação."
            ),
            reason="transport",
            hold_cursor=True,
        )
        return SyncRequest.Status.FAILED
    except (SefazDistributionError, DistributionParseError, FiscalStorageError):
        _finish_failed(
            sync_request_id=claimed.request_id,
            now=now,
            detail=(
                "A resposta fiscal não pôde ser concluída com segurança. "
                "Aguarde uma hora antes de uma nova solicitação."
            ),
            reason="response_or_storage",
            hold_cursor=True,
        )
        return SyncRequest.Status.FAILED
    except Exception:
        _finish_failed(
            sync_request_id=claimed.request_id,
            now=now,
            detail=(
                "A sincronização falhou antes de ser concluída. "
                "Revise o histórico antes de solicitar novamente."
            ),
            reason="unexpected",
            hold_cursor=True,
        )
        return SyncRequest.Status.FAILED

    _finish_succeeded(
        sync_request_id=claimed.request_id,
        batch=batch,
        now=now,
    )
    return SyncRequest.Status.SUCCEEDED


def _claim_sync_request(
    *, sync_request_id: int, now: datetime
) -> ClaimedSynchronization | str:
    with transaction.atomic():
        sync_request = (
            SyncRequest.objects.select_for_update()
            .select_related("company", "requested_by")
            .filter(pk=sync_request_id)
            .first()
        )
        if sync_request is None:
            return "missing"
        if sync_request.status != SyncRequest.Status.QUEUED:
            return sync_request.status

        control = NsuControl.objects.select_for_update().get(
            company_id=sync_request.company_id,
            environment=sync_request.environment,
            service="nfe_distribution",
        )
        if control.next_allowed_at is not None and control.next_allowed_at > now:
            sync_request.status = SyncRequest.Status.WAITING
            sync_request.result_detail = (
                "Consulta permitida após "
                f"{control.next_allowed_at.isoformat()}."
            )
            sync_request.save(update_fields=("status", "result_detail"))
            AuditLog.objects.create(
                actor=sync_request.requested_by,
                action="fiscal.sync_request_waiting",
                target=f"fiscal.sync_request:{sync_request.pk}",
                payload={
                    "company_id": sync_request.company_id,
                    "environment": sync_request.environment,
                },
            )
            return SyncRequest.Status.WAITING

        certificate = (
            DigitalCertificate.objects.filter(
                company_id=sync_request.company_id,
                status=DigitalCertificate.Status.ACTIVE,
                not_valid_before__lte=now,
                not_valid_after__gt=now,
            )
            .order_by("-not_valid_after", "-created_at")
            .first()
        )
        if certificate is None:
            _finish_request_without_remote_call(
                sync_request=sync_request,
                now=now,
                detail=(
                    "Não há certificado A1 ativo e válido para esta empresa. "
                    "A consulta não foi enviada à SEFAZ."
                ),
                reason="certificate_unavailable",
            )
            return SyncRequest.Status.FAILED

        sync_request.status = SyncRequest.Status.RUNNING
        sync_request.started_at = now
        sync_request.result_detail = "Consulta em execução no worker fiscal."
        sync_request.save(update_fields=("status", "started_at", "result_detail"))
        AuditLog.objects.create(
            actor=sync_request.requested_by,
            action="fiscal.sync_request_started",
            target=f"fiscal.sync_request:{sync_request.pk}",
            payload={
                "company_id": sync_request.company_id,
                "environment": sync_request.environment,
            },
        )
        return ClaimedSynchronization(
            request_id=sync_request.pk,
            company_id=sync_request.company_id,
            tax_identifier=sync_request.company.tax_identifier,
            environment=sync_request.environment,
            control_id=control.pk,
            last_nsu=control.last_nsu,
            certificate=certificate,
        )


def _finish_succeeded(
    *, sync_request_id: int, batch: DistributionBatch, now: datetime
) -> None:
    with transaction.atomic():
        sync_request = (
            SyncRequest.objects.select_for_update()
            .select_related("requested_by")
            .filter(pk=sync_request_id)
            .first()
        )
        if sync_request is None or sync_request.status != SyncRequest.Status.RUNNING:
            return
        sync_request.status = SyncRequest.Status.SUCCEEDED
        sync_request.finished_at = now
        sync_request.result_detail = _success_detail(batch)
        sync_request.save(update_fields=("status", "finished_at", "result_detail"))
        _record_policy_outcome(
            company_id=sync_request.company_id,
            now=now,
            result=batch.status_code,
            failed=False,
        )
        if batch.status_code == "656":
            open_operation_alert(
                company_id=sync_request.company_id,
                code="sefaz_consumption_block",
                severity="warning",
                title="Consulta bloqueada temporariamente pela SEFAZ",
                message=(
                    "A SEFAZ respondeu cStat 656. O sistema respeitará a janela "
                    "de espera antes de uma nova consulta."
                ),
                context={"status_code": batch.status_code},
            )
        AuditLog.objects.create(
            actor=sync_request.requested_by,
            action="fiscal.sync_request_succeeded",
            target=f"fiscal.sync_request:{sync_request.pk}",
            payload={
                "company_id": sync_request.company_id,
                "environment": sync_request.environment,
                "batch_id": batch.pk,
                "status_code": batch.status_code,
                "document_count": batch.document_count,
            },
        )


def _finish_failed(
    *,
    sync_request_id: int,
    now: datetime,
    detail: str,
    reason: str,
    hold_cursor: bool,
) -> None:
    with transaction.atomic():
        sync_request = (
            SyncRequest.objects.select_for_update()
            .select_related("requested_by")
            .filter(pk=sync_request_id)
            .first()
        )
        if sync_request is None or sync_request.status != SyncRequest.Status.RUNNING:
            return
        if hold_cursor:
            control = NsuControl.objects.select_for_update().get(
                company_id=sync_request.company_id,
                environment=sync_request.environment,
                service="nfe_distribution",
            )
            _apply_uncertain_response_hold(control=control, now=now)
        sync_request.status = SyncRequest.Status.FAILED
        sync_request.finished_at = now
        sync_request.result_detail = detail
        sync_request.save(update_fields=("status", "finished_at", "result_detail"))
        _record_policy_outcome(
            company_id=sync_request.company_id,
            now=now,
            result="failed",
            failed=True,
        )
        open_operation_alert(
            company_id=sync_request.company_id,
            code="sync_execution_failed",
            severity="critical",
            title="Sincronização fiscal não concluída",
            message=detail,
            context={"environment": sync_request.environment, "reason": reason},
        )
        AuditLog.objects.create(
            actor=sync_request.requested_by,
            action="fiscal.sync_request_failed",
            target=f"fiscal.sync_request:{sync_request.pk}",
            payload={
                "company_id": sync_request.company_id,
                "environment": sync_request.environment,
                "reason": reason,
            },
        )


def _finish_request_without_remote_call(
    *,
    sync_request: SyncRequest,
    now: datetime,
    detail: str,
    reason: str,
) -> None:
    sync_request.status = SyncRequest.Status.FAILED
    sync_request.finished_at = now
    sync_request.result_detail = detail
    sync_request.save(update_fields=("status", "finished_at", "result_detail"))
    _record_policy_outcome(
        company_id=sync_request.company_id,
        now=now,
        result="failed",
        failed=True,
    )
    open_operation_alert(
        company_id=sync_request.company_id,
        code="certificate_unavailable",
        severity="critical",
        title="Certificado A1 indisponível",
        message=detail,
        context={"environment": sync_request.environment, "reason": reason},
    )
    AuditLog.objects.create(
        actor=sync_request.requested_by,
        action="fiscal.sync_request_failed",
        target=f"fiscal.sync_request:{sync_request.pk}",
        payload={
            "company_id": sync_request.company_id,
            "environment": sync_request.environment,
            "reason": reason,
        },
    )


def _record_policy_outcome(
    *, company_id: int, now: datetime, result: str, failed: bool
) -> None:
    policy = (
        SyncPolicy.objects.select_for_update().filter(company_id=company_id).first()
    )
    if policy is None:
        return
    policy.last_finished_at = now
    policy.last_result = result
    policy.failure_count = policy.failure_count + 1 if failed else 0
    policy.save(
        update_fields=(
            "last_finished_at",
            "last_result",
            "failure_count",
            "updated_at",
        )
    )


def _apply_uncertain_response_hold(*, control: NsuControl, now: datetime) -> None:
    hold_until = now + timedelta(hours=1)
    if control.next_allowed_at is not None and control.next_allowed_at > hold_until:
        return
    control.next_allowed_at = hold_until
    control.blocked_reason = (
        "Resultado da consulta não confirmado; aguardar uma hora antes de repetir."
    )
    control.save(update_fields=("next_allowed_at", "blocked_reason", "updated_at"))


def _success_detail(batch: DistributionBatch) -> str:
    detail = f"SEFAZ respondeu cStat {batch.status_code}."
    if batch.reason:
        detail = f"{detail} {batch.reason}"
    if batch.document_count:
        detail = f"{detail} {batch.document_count} documento(s) arquivado(s)."
    return detail
