from django.conf import settings
from django.db import models

from apps.organizations.models import ClientCompany


class AuditLog(models.Model):
    """Append-only operational record; secret material must never enter payload."""

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="audit_entries",
        null=True,
        blank=True,
    )
    action = models.CharField("ação", max_length=100)
    target = models.CharField("alvo", max_length=255)
    correlation_id = models.UUIDField("correlação", null=True, blank=True)
    payload = models.JSONField("dados não sensíveis", default=dict, blank=True)
    created_at = models.DateTimeField("criado em", auto_now_add=True)

    class Meta:
        verbose_name = "registro de auditoria"
        verbose_name_plural = "registros de auditoria"
        ordering = ("-created_at",)

    def __str__(self) -> str:
        return f"{self.action}: {self.target}"


class OperationAlert(models.Model):
    """Tenant-scoped operational exception that requires human review."""

    class Severity(models.TextChoices):
        INFO = "info", "Informativo"
        WARNING = "warning", "Atenção"
        CRITICAL = "critical", "Crítico"

    class Status(models.TextChoices):
        OPEN = "open", "Aberto"
        RESOLVED = "resolved", "Resolvido"

    company = models.ForeignKey(
        ClientCompany,
        on_delete=models.PROTECT,
        related_name="operation_alerts",
    )
    code = models.CharField("código", max_length=80)
    severity = models.CharField(
        "gravidade",
        max_length=16,
        choices=Severity,
        default=Severity.WARNING,
    )
    title = models.CharField("título", max_length=160)
    message = models.TextField("mensagem")
    context = models.JSONField("contexto não sensível", default=dict, blank=True)
    status = models.CharField(
        "situação",
        max_length=16,
        choices=Status,
        default=Status.OPEN,
    )
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="resolved_operation_alerts",
        null=True,
        blank=True,
    )
    resolved_at = models.DateTimeField("resolvido em", null=True, blank=True)
    resolution_note = models.TextField("registro da resolução", blank=True)
    created_at = models.DateTimeField("criado em", auto_now_add=True)
    updated_at = models.DateTimeField("atualizado em", auto_now=True)

    class Meta:
        verbose_name = "alerta operacional"
        verbose_name_plural = "alertas operacionais"
        ordering = ("-created_at",)
        constraints = [
            models.UniqueConstraint(
                fields=("company", "code"),
                condition=models.Q(status="open"),
                name="one_open_operation_alert_per_company_code",
            ),
        ]
        indexes = [
            models.Index(
                fields=("company", "status", "created_at"),
                name="operations__company_236d50_idx",
            ),
            models.Index(
                fields=("severity", "status"),
                name="operations__severit_7f9c8d_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.company} — {self.title}"
