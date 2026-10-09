import uuid

from django.conf import settings
from django.db import models
from django.db.models import Q

from apps.organizations.models import ClientCompany


class DigitalCertificate(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "active", "Ativo"
        REPLACED = "replaced", "Substituído"
        EXPIRED = "expired", "Expirado"
        INVALID = "invalid", "Inválido"

    company = models.ForeignKey(
        ClientCompany,
        on_delete=models.PROTECT,
        related_name="digital_certificates",
    )
    storage_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    encrypted_path = models.CharField(max_length=255, unique=True, editable=False)
    encrypted_password_path = models.CharField(
        max_length=255,
        unique=True,
        editable=False,
    )
    password_hash = models.CharField(max_length=255, editable=False)
    filename = models.CharField("nome original", max_length=255)
    content_sha256 = models.CharField(max_length=64, editable=False)
    certificate_fingerprint_sha256 = models.CharField(max_length=64, editable=False)
    serial_number = models.CharField(max_length=128, editable=False)
    subject = models.TextField(editable=False)
    issuer = models.TextField(editable=False)
    not_valid_before = models.DateTimeField(editable=False)
    not_valid_after = models.DateTimeField(editable=False)
    status = models.CharField(max_length=16, choices=Status, default=Status.ACTIVE)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="uploaded_certificates",
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    replaced_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "certificado digital"
        verbose_name_plural = "certificados digitais"
        ordering = ("-not_valid_after", "-created_at")
        constraints = [
            models.UniqueConstraint(
                fields=("company",),
                condition=Q(status="active"),
                name="one_active_certificate_per_company",
            ),
        ]
        indexes = [
            models.Index(fields=("company", "status")),
            models.Index(fields=("not_valid_after",)),
        ]

    def __str__(self) -> str:
        return f"{self.company} — {self.serial_number}"


class CertificateUpload(models.Model):
    class Status(models.TextChoices):
        SUBMITTED = "submitted", "Recebido"
        PROCESSING = "processing", "Em processamento"
        COMPLETED = "completed", "Concluído"
        FAILED = "failed", "Falhou"
        EXPIRED = "expired", "Expirado"

    company = models.ForeignKey(
        ClientCompany,
        on_delete=models.PROTECT,
        related_name="certificate_uploads",
    )
    request_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    filename = models.CharField("nome original", max_length=255)
    encrypted_payload = models.BinaryField(editable=False, null=True, blank=True)
    encrypted_password = models.BinaryField(editable=False, null=True, blank=True)
    status = models.CharField(
        "situação",
        max_length=16,
        choices=Status,
        default=Status.SUBMITTED,
    )
    error_message = models.CharField("erro", max_length=255, blank=True)
    certificate = models.ForeignKey(
        DigitalCertificate,
        on_delete=models.SET_NULL,
        related_name="upload_requests",
        null=True,
        blank=True,
    )
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="certificate_upload_requests",
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    started_at = models.DateTimeField(null=True, blank=True)
    processed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "envio de certificado"
        verbose_name_plural = "envios de certificados"
        constraints = [
            models.UniqueConstraint(
                fields=("company",),
                condition=Q(status__in=("submitted", "processing")),
                name="one_active_certificate_upload_per_company",
            ),
        ]
        indexes = [
            models.Index(
                fields=("company", "status"),
                name="certificat_company_7b096c_idx",
            ),
            models.Index(
                fields=("expires_at", "status"),
                name="certificat_expires_57b761_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.company} — {self.get_status_display()}"
