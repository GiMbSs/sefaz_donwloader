"""Shared, non-secret operational alert use cases."""

from __future__ import annotations

from dataclasses import dataclass

from django.db import IntegrityError, transaction

from apps.operations.models import OperationAlert


@dataclass(frozen=True)
class OperationAlertReceipt:
    alert: OperationAlert
    created: bool


def open_operation_alert(
    *,
    company_id: int,
    code: str,
    severity: str,
    title: str,
    message: str,
    context: dict[str, str | int] | None = None,
) -> OperationAlertReceipt:
    """Open or refresh one unresolved alert without leaking fiscal secrets."""
    if severity not in OperationAlert.Severity.values:
        raise ValueError("Gravidade de alerta inválida.")
    defaults = {
        "severity": severity,
        "title": title,
        "message": message,
        "context": context or {},
    }
    try:
        with transaction.atomic():
            alert, created = OperationAlert.objects.get_or_create(
                company_id=company_id,
                code=code,
                status=OperationAlert.Status.OPEN,
                defaults=defaults,
            )
    except IntegrityError:
        alert = OperationAlert.objects.select_for_update().get(
            company_id=company_id,
            code=code,
            status=OperationAlert.Status.OPEN,
        )
        created = False

    if not created:
        alert.severity = severity
        alert.title = title
        alert.message = message
        alert.context = context or {}
        alert.save(
            update_fields=("severity", "title", "message", "context", "updated_at")
        )
    return OperationAlertReceipt(alert=alert, created=created)
