from django.db import models

from apps.organizations.models import ClientCompany


class SyncPolicy(models.Model):
    class Mode(models.TextChoices):
        DAILY = "daily", "Automática diária"
        MANUAL = "manual", "Manual"
        HYBRID = "hybrid", "Híbrida"

    company = models.OneToOneField(ClientCompany, on_delete=models.CASCADE, related_name="sync_policy")
    mode = models.CharField("modo", max_length=16, choices=Mode, default=Mode.DAILY)
    scheduled_time = models.TimeField("horário diário", null=True, blank=True)
    timezone = models.CharField("fuso horário", max_length=64, default="America/Fortaleza")
    weekdays = models.JSONField("dias ativos", default=list, blank=True)
    is_active = models.BooleanField("ativa", default=True)
    last_requested_at = models.DateTimeField("última solicitação", null=True, blank=True)
    last_finished_at = models.DateTimeField("última conclusão", null=True, blank=True)
    last_result = models.CharField("último resultado", max_length=32, blank=True)
    failure_count = models.PositiveIntegerField("falhas consecutivas", default=0)
    created_at = models.DateTimeField("criada em", auto_now_add=True)
    updated_at = models.DateTimeField("atualizada em", auto_now=True)

    class Meta:
        verbose_name = "política de sincronização"
        verbose_name_plural = "políticas de sincronização"


class NsuControl(models.Model):
    class Environment(models.TextChoices):
        PRODUCTION = "production", "Produção"
        HOMOLOGATION = "homologation", "Homologação"

    company = models.ForeignKey(ClientCompany, on_delete=models.PROTECT, related_name="nsu_controls")
    environment = models.CharField("ambiente", max_length=16, choices=Environment)
    service = models.CharField("serviço", max_length=64, default="nfe_distribution")
    last_nsu = models.CharField("último NSU", max_length=15, blank=True)
    maximum_nsu = models.CharField("máximo NSU", max_length=15, blank=True)
    next_allowed_at = models.DateTimeField("próxima consulta permitida", null=True, blank=True)
    blocked_reason = models.CharField("motivo do bloqueio", max_length=255, blank=True)
    last_status_code = models.CharField("último cStat", max_length=8, blank=True)
    updated_at = models.DateTimeField("atualizado em", auto_now=True)

    class Meta:
        verbose_name = "controle de NSU"
        verbose_name_plural = "controles de NSU"
        constraints = [
            models.UniqueConstraint(
                fields=("company", "environment", "service"),
                name="unique_nsu_control_per_company_environment_service",
            ),
        ]
        indexes = [models.Index(fields=("next_allowed_at",))]


class SyncRequest(models.Model):
    class Trigger(models.TextChoices):
        SCHEDULED = "scheduled", "Agendada"
        MANUAL = "manual", "Manual"

    class Status(models.TextChoices):
        QUEUED = "queued", "Na fila"
        RUNNING = "running", "Em execução"
        WAITING = "waiting", "Aguardando SEFAZ"
        SUCCEEDED = "succeeded", "Concluída"
        FAILED = "failed", "Falhou"
        COALESCED = "coalesced", "Agrupada"

    company = models.ForeignKey(ClientCompany, on_delete=models.PROTECT, related_name="sync_requests")
    environment = models.CharField("ambiente", max_length=16, choices=NsuControl.Environment)
    trigger = models.CharField("origem", max_length=16, choices=Trigger)
    status = models.CharField("situação", max_length=16, choices=Status, default=Status.QUEUED)
    requested_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        related_name="requested_syncs",
        null=True,
        blank=True,
    )
    requested_at = models.DateTimeField("solicitada em", auto_now_add=True)
    started_at = models.DateTimeField("iniciada em", null=True, blank=True)
    finished_at = models.DateTimeField("finalizada em", null=True, blank=True)
    result_detail = models.TextField("detalhe do resultado", blank=True)

    class Meta:
        verbose_name = "solicitação de sincronização"
        verbose_name_plural = "solicitações de sincronização"
        indexes = [models.Index(fields=("company", "status", "requested_at"))]

