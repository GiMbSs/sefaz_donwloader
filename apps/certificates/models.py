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
    sealed_password = models.TextField(editable=False)
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
                condition=Q(status=Status.ACTIVE),
                name="one_active_certificate_per_company",
            ),
        ]
        indexes = [
            models.Index(fields=("company", "status")),
            models.Index(fields=("not_valid_after",)),
        ]

    def __str__(self) -> str:
        return f"{self.company} — {self.serial_number}"

