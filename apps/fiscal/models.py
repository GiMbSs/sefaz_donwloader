from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from apps.organizations.models import ClientCompany


class SyncPolicy(models.Model):
    class Mode(models.TextChoices):
        AUTOMATIC = "automatic", "Automática"
        MANUAL = "manual", "Manual"
        HYBRID = "hybrid", "Híbrida"

    class Frequency(models.TextChoices):
        DAILY = "daily", "Diária"
        WEEKLY = "weekly", "Semanal"
        MONTHLY = "monthly", "Mensal"

    company = models.OneToOneField(ClientCompany, on_delete=models.CASCADE, related_name="sync_policy")
    mode = models.CharField("modo", max_length=16, choices=Mode, default=Mode.AUTOMATIC)
    frequency = models.CharField(
        "recorrência",
        max_length=16,
        choices=Frequency,
        default=Frequency.DAILY,
    )
    scheduled_time = models.TimeField("horário", null=True, blank=True)
    timezone = models.CharField("fuso horário", max_length=64, default="America/Fortaleza")
    weekdays = models.JSONField("dias da semana", default=list, blank=True)
    monthday = models.PositiveSmallIntegerField("dia do mês", default=1)
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

    def clean(self) -> None:
        super().clean()
        try:
            ZoneInfo(self.timezone)
        except ZoneInfoNotFoundError as error:
            raise ValidationError(
                {"timezone": "Informe um fuso horário IANA válido."}
            ) from error
        if self.mode in {self.Mode.AUTOMATIC, self.Mode.HYBRID} and self.scheduled_time is None:
            raise ValidationError({"scheduled_time": "Informe o horário da sincronização automática."})
        if not isinstance(self.weekdays, list) or any(
            not isinstance(day, int) or day not in range(7) for day in self.weekdays
        ):
            raise ValidationError(
                {"weekdays": "Use dias da semana entre 0 (segunda) e 6 (domingo)."}
            )
        if self.frequency == self.Frequency.WEEKLY and not self.weekdays:
            raise ValidationError(
                {"weekdays": "Selecione ao menos um dia para a recorrência semanal."}
            )
        if not 1 <= self.monthday <= 31:
            raise ValidationError({"monthday": "Informe um dia entre 1 e 31."})


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
        indexes = [
            models.Index(
                fields=("next_allowed_at",),
                name="fiscal_nsuc_next_al_fc24e4_idx",
            )
        ]


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
        indexes = [
            models.Index(
                fields=("company", "status", "requested_at"),
                name="fiscal_sync_company_441318_idx",
            )
        ]
        constraints = [
            models.UniqueConstraint(
                fields=("company", "environment"),
                condition=Q(status__in=("queued", "running", "waiting")),
                name="one_active_sync_request_per_company_environment",
            ),
        ]


class DistributionBatch(models.Model):
    class ProcessingStatus(models.TextChoices):
        RECEIVED = "received", "Recebido"
        PROCESSED = "processed", "Processado"
        INVALID = "invalid", "Inválido"
        FAILED = "failed", "Falhou"

    company = models.ForeignKey(ClientCompany, on_delete=models.PROTECT, related_name="distribution_batches")
    nsu_control = models.ForeignKey(NsuControl, on_delete=models.PROTECT, related_name="batches")
    sync_request = models.ForeignKey(
        SyncRequest,
        on_delete=models.SET_NULL,
        related_name="batches",
        null=True,
        blank=True,
    )
    response_sha256 = models.CharField(max_length=64)
    raw_response_path = models.CharField(max_length=255)
    soap_response_path = models.CharField(max_length=255, blank=True)
    status_code = models.CharField(max_length=8)
    reason = models.TextField(blank=True)
    response_at = models.DateTimeField(null=True, blank=True)
    returned_last_nsu = models.CharField(max_length=15, blank=True)
    returned_max_nsu = models.CharField(max_length=15, blank=True)
    document_count = models.PositiveSmallIntegerField(default=0)
    processing_status = models.CharField(
        max_length=16,
        choices=ProcessingStatus,
        default=ProcessingStatus.RECEIVED,
    )
    processing_error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "lote de distribuição"
        verbose_name_plural = "lotes de distribuição"
        constraints = [
            models.UniqueConstraint(
                fields=("company", "response_sha256"),
                name="unique_distribution_response_per_company",
            ),
        ]
        indexes = [
            models.Index(
                fields=("company", "created_at"),
                name="fiscal_dist_company_2055c1_idx",
            ),
            models.Index(
                fields=("status_code", "processing_status"),
                name="fiscal_dist_status__d54f0e_idx",
            ),
        ]


class FiscalDocument(models.Model):
    class Kind(models.TextChoices):
        SUMMARY = "summary", "Resumo"
        COMPLETE = "complete", "Completo"
        EVENT = "event", "Evento"
        UNKNOWN = "unknown", "Desconhecido"

    class ValidationStatus(models.TextChoices):
        PENDING_SCHEMA = "pending_schema", "Schema pendente"
        VALID = "valid", "Válido"
        INVALID = "invalid", "Inválido"

    company = models.ForeignKey(ClientCompany, on_delete=models.PROTECT, related_name="fiscal_documents")
    access_key = models.CharField(max_length=44)
    model = models.CharField(max_length=2, blank=True)
    kind = models.CharField(max_length=16, choices=Kind, default=Kind.UNKNOWN)
    schema_name = models.CharField(max_length=128)
    document_root = models.CharField(max_length=80)
    xml_sha256 = models.CharField(max_length=64)
    xml_path = models.CharField(max_length=255)
    validation_status = models.CharField(
        max_length=16,
        choices=ValidationStatus,
        default=ValidationStatus.PENDING_SCHEMA,
    )
    validation_error = models.TextField(blank=True)
    first_received_at = models.DateTimeField(auto_now_add=True)
    last_received_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "documento fiscal"
        verbose_name_plural = "documentos fiscais"
        constraints = [
            models.UniqueConstraint(
                fields=("company", "access_key"),
                name="unique_fiscal_document_per_company_access_key",
            ),
        ]
        indexes = [
            models.Index(
                fields=("company", "model", "kind"),
                name="fiscal_fisc_company_6e246d_idx",
            ),
            models.Index(
                fields=("validation_status",),
                name="fiscal_fisc_validat_59309c_idx",
            ),
        ]


class DistributionItem(models.Model):
    class ProcessingStatus(models.TextChoices):
        STORED = "stored", "Armazenado"
        REJECTED = "rejected", "Rejeitado"
        DUPLICATE = "duplicate", "Duplicado"

    batch = models.ForeignKey(DistributionBatch, on_delete=models.CASCADE, related_name="items")
    nsu = models.CharField(max_length=15)
    schema_name = models.CharField(max_length=128)
    compressed_sha256 = models.CharField(max_length=64)
    xml_sha256 = models.CharField(max_length=64, blank=True)
    fiscal_document = models.ForeignKey(
        FiscalDocument,
        on_delete=models.SET_NULL,
        related_name="distribution_items",
        null=True,
        blank=True,
    )
    processing_status = models.CharField(max_length=16, choices=ProcessingStatus)
    processing_error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "item de distribuição"
        verbose_name_plural = "itens de distribuição"
        constraints = [
            models.UniqueConstraint(fields=("batch", "nsu"), name="unique_nsu_per_distribution_batch"),
        ]
        indexes = [models.Index(fields=("nsu",), name="fiscal_dist_nsu_7fb3db_idx")]
