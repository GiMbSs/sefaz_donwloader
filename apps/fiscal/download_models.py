"""Persistent ATF download domain, independent of legacy NSU tables."""

import uuid
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Q
from django.utils import timezone

from .atf.profiles import DOCUMENT_CHOICES, document_profile

ACTIVE_REQUEST_STATES = ("queued", "running", "waiting")
REQUEST_STATES = (
    "queued",
    "running",
    "waiting",
    "succeeded",
    "partial",
    "empty",
    "failed",
    "cancelled",
)
PART_STATES = (
    "queued",
    "submitting",
    "waiting",
    "ambiguous",
    "downloading",
    "validating",
    "succeeded",
    "empty",
    "failed",
)


def default_formats() -> list[str]:
    return ["xml", "txt"]


def default_document_models() -> list[str]:
    return ["55"]


class AtfModel(models.Model):
    class Meta:
        abstract = True

    def __str__(self) -> str:
        return f"{self._meta.verbose_name}: {self.pk}"


class DownloadPolicy(AtfModel):
    company = models.OneToOneField(
        "organizations.ClientCompany",
        on_delete=models.CASCADE,
        related_name="download_policy",
    )
    mode = models.CharField(
        max_length=16,
        default="manual",
        choices=[
            ("manual", "Manual"),
            ("automatic", "Automática"),
            ("hybrid", "Híbrida"),
        ],
    )
    frequency = models.CharField(
        max_length=16,
        default="daily",
        choices=[("daily", "Diária"), ("weekly", "Semanal"), ("monthly", "Mensal")],
    )
    scheduled_time = models.TimeField(null=True, blank=True)
    timezone = models.CharField(max_length=64, default="America/Fortaleza")
    weekdays = models.JSONField(default=list, blank=True)
    monthday = models.PositiveSmallIntegerField(default=1)
    is_active = models.BooleanField(default=False)
    period_strategy = models.CharField(
        max_length=24,
        default="previous_day",
        choices=[
            ("previous_day", "Dia anterior"),
            ("previous_month", "Mês anterior"),
            ("rolling_days", "Últimos dias completos"),
        ],
    )
    rolling_days = models.PositiveSmallIntegerField(
        default=7, validators=[MinValueValidator(1)]
    )
    formats = models.JSONField(default=default_formats)
    document_models = models.JSONField(default=default_document_models)
    legacy_policy_id = models.PositiveBigIntegerField(
        null=True, blank=True, unique=True
    )
    last_scheduled_slot = models.CharField(max_length=64, blank=True)
    last_requested_at = models.DateTimeField(null=True, blank=True)
    last_finished_at = models.DateTimeField(null=True, blank=True)
    last_result = models.CharField(max_length=32, blank=True)
    failure_count = models.PositiveIntegerField(default=0)

    def clean(self) -> None:
        super().clean()
        if (
            not isinstance(self.document_models, list)
            or not self.document_models
            or any(model not in {"55", "65"} for model in self.document_models)
        ):
            raise ValidationError(
                {"document_models": "Selecione NF-e, NFC-e ou ambos."}
            )
        try:
            ZoneInfo(self.timezone)
        except (ZoneInfoNotFoundError, ValueError) as error:
            raise ValidationError({"timezone": "Fuso horário inválido."}) from error
        if self.mode != "manual" and self.scheduled_time is None:
            raise ValidationError({"scheduled_time": "Informe o horário."})
        if not isinstance(self.weekdays, list) or any(
            type(day) is not int or day not in range(7) for day in self.weekdays
        ):
            raise ValidationError({"weekdays": "Use dias de 0 a 6."})
        if self.frequency == "weekly" and not self.weekdays:
            raise ValidationError({"weekdays": "Selecione os dias da semana."})
        if not 1 <= self.monthday <= 31:
            raise ValidationError({"monthday": "Use dia de 1 a 31."})
        if (
            not isinstance(self.formats, list)
            or not self.formats
            or set(self.formats) - {"xml", "txt"}
        ):
            raise ValidationError({"formats": "Selecione XML, TXT ou ambos."})


class DownloadRequest(AtfModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    company = models.ForeignKey(
        "organizations.ClientCompany",
        on_delete=models.PROTECT,
        related_name="download_requests",
    )
    policy = models.ForeignKey(
        DownloadPolicy, on_delete=models.SET_NULL, null=True, blank=True
    )
    start_date = models.DateField()
    end_date = models.DateField()
    formats = models.JSONField(default=default_formats)
    document_model = models.CharField(
        max_length=2, default="55", choices=DOCUMENT_CHOICES
    )
    trigger = models.CharField(max_length=16, default="manual")
    status = models.CharField(
        max_length=16, default="queued", choices=[(s, s) for s in REQUEST_STATES]
    )
    active_key = models.CharField(max_length=64)
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True
    )
    repeat_of = models.ForeignKey(
        "self", on_delete=models.SET_NULL, null=True, blank=True
    )
    created_at = models.DateTimeField(auto_now_add=True)
    requested_on = models.DateField(default=timezone.localdate)
    finished_at = models.DateTimeField(null=True, blank=True)
    result_detail = models.TextField(blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("active_key",),
                condition=Q(status__in=ACTIVE_REQUEST_STATES),
                name="unique_active_atf_download",
            )
        ]
        ordering = ("-created_at",)


class DownloadPart(AtfModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    request = models.ForeignKey(
        DownloadRequest, on_delete=models.CASCADE, related_name="parts"
    )
    start_date = models.DateField()
    end_date = models.DateField()
    format = models.CharField(max_length=3, choices=[("xml", "XML"), ("txt", "TXT")])
    status = models.CharField(
        max_length=16, default="queued", choices=[(s, s) for s in PART_STATES]
    )
    baseline_ids = models.JSONField(default=list, blank=True)
    remote_account_key = models.CharField(max_length=64, blank=True)
    remote_parent_id = models.CharField(max_length=64, blank=True)
    candidates = models.JSONField(default=list, blank=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    deadline_at = models.DateTimeField(null=True, blank=True)
    next_poll_at = models.DateTimeField(null=True, blank=True)
    step_version = models.PositiveIntegerField(default=0)
    retry_count = models.PositiveSmallIntegerField(default=0)
    retry_cycle = models.PositiveIntegerField(default=0)
    poll_count = models.PositiveIntegerField(default=0)
    error_code = models.CharField(max_length=64, blank=True)
    result_detail = models.TextField(blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("request", "start_date", "end_date", "format"),
                name="unique_atf_download_part",
            )
        ]
        ordering = ("start_date", "format")


class DownloadAttempt(AtfModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    part = models.ForeignKey(
        DownloadPart, on_delete=models.CASCADE, related_name="attempts"
    )
    operation = models.CharField(max_length=24)
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    outcome = models.CharField(max_length=24, blank=True)
    error_code = models.CharField(max_length=64, blank=True)
    submission_certainty = models.CharField(max_length=16, default="not_sent")


class RemoteResultBinding(AtfModel):
    part = models.ForeignKey(
        DownloadPart, on_delete=models.PROTECT, related_name="remote_bindings"
    )
    remote_account_key = models.CharField(max_length=64)
    parent_message_id = models.CharField(max_length=64)
    confirmed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("remote_account_key", "parent_message_id"),
                name="unique_atf_remote_group",
            )
        ]


class DownloadArchive(AtfModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    part = models.ForeignKey(
        DownloadPart, on_delete=models.PROTECT, related_name="archives"
    )
    remote_account_key = models.CharField(max_length=64)
    message_id = models.CharField(max_length=64)
    attachment_index = models.PositiveIntegerField()
    filename = models.CharField(max_length=255)
    path = models.CharField(max_length=1024)
    sha256 = models.CharField(max_length=64)
    byte_count = models.PositiveBigIntegerField()
    validation_status = models.CharField(max_length=24, default="valid")
    warnings = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("remote_account_key", "message_id", "attachment_index"),
                name="unique_atf_remote_attachment",
            )
        ]


class InvoiceDocument(AtfModel):
    company = models.ForeignKey(
        "organizations.ClientCompany", on_delete=models.PROTECT, related_name="invoices"
    )
    access_key = models.CharField(max_length=44)
    number = models.PositiveIntegerField(null=True, blank=True)
    model = models.CharField(max_length=2, default="55")
    issued_on = models.DateField()
    first_received_at = models.DateTimeField(auto_now_add=True)
    last_received_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("company", "access_key"), name="unique_atf_invoice"
            )
        ]

    @property
    def document_label(self) -> str:
        return document_profile(self.model).label


class InvoiceXmlVersion(AtfModel):
    document = models.ForeignKey(
        InvoiceDocument, on_delete=models.PROTECT, related_name="versions"
    )
    sha256 = models.CharField(max_length=64)
    path = models.CharField(max_length=1024)
    validation_status = models.CharField(max_length=24, default="pending_schema")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("document", "sha256"), name="unique_atf_invoice_xml"
            )
        ]


class FiscalEvent(AtfModel):
    company = models.ForeignKey(
        "organizations.ClientCompany",
        on_delete=models.PROTECT,
        related_name="fiscal_events",
    )
    access_key = models.CharField(max_length=44)
    event_type = models.CharField(max_length=6)
    sequence = models.PositiveIntegerField()
    sha256 = models.CharField(max_length=64)
    path = models.CharField(max_length=1024)
    validation_status = models.CharField(max_length=24, default="pending_schema")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("company", "access_key", "event_type", "sequence", "sha256"),
                name="unique_atf_event_xml",
            )
        ]


class ArchiveMember(AtfModel):
    archive = models.ForeignKey(
        DownloadArchive, on_delete=models.CASCADE, related_name="members"
    )
    name = models.CharField(max_length=1024)
    kind = models.CharField(max_length=16)
    sha256 = models.CharField(max_length=64)
    byte_count = models.PositiveBigIntegerField()
    path = models.CharField(max_length=1024, blank=True)
    invoice_version = models.ForeignKey(
        InvoiceXmlVersion, on_delete=models.PROTECT, null=True, blank=True
    )
    event = models.ForeignKey(
        FiscalEvent, on_delete=models.PROTECT, null=True, blank=True
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("archive", "name"), name="unique_atf_archive_member"
            )
        ]


class AtfAccessLease(AtfModel):
    scope = models.CharField(primary_key=True, max_length=80)
    owner = models.UUIDField(default=uuid.uuid4)
    generation = models.PositiveBigIntegerField(default=1)
    part = models.ForeignKey(
        DownloadPart, on_delete=models.SET_NULL, null=True, blank=True
    )
    expires_at = models.DateTimeField()
    next_poll_at = models.DateTimeField(null=True, blank=True)


class RemoteSubmissionBarrier(AtfModel):
    scope = models.CharField(primary_key=True, max_length=80)
    part = models.ForeignKey(
        DownloadPart, on_delete=models.PROTECT, related_name="submission_barriers"
    )
    attempt = models.ForeignKey(DownloadAttempt, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)
