from django.conf import settings
from django.db import models


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

