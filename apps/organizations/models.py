from django.db import models

from .validators import normalize_tax_identifier, validate_tax_identifier


class AccountingOffice(models.Model):
    """Tenant representing the accounting office operating this installation."""

    legal_name = models.CharField("razão social", max_length=255)
    tax_identifier = models.CharField(
        "CNPJ",
        max_length=14,
        unique=True,
        validators=[validate_tax_identifier],
    )
    created_at = models.DateTimeField("criado em", auto_now_add=True)

    class Meta:
        verbose_name = "escritório contábil"
        verbose_name_plural = "escritórios contábeis"

    def __str__(self) -> str:
        return self.legal_name

    def clean(self) -> None:
        super().clean()
        self.tax_identifier = normalize_tax_identifier(self.tax_identifier)


class OfficeMembership(models.Model):
    class Role(models.TextChoices):
        ADMIN = "admin", "Administrador"
        OPERATOR = "operator", "Operador"

    office = models.ForeignKey(
        AccountingOffice,
        on_delete=models.CASCADE,
        related_name="memberships",
    )
    user = models.ForeignKey(
        "accounts.User",
        on_delete=models.CASCADE,
        related_name="office_memberships",
    )
    role = models.CharField(
        "perfil",
        max_length=16,
        choices=Role,
        default=Role.OPERATOR,
    )
    is_active = models.BooleanField("ativa", default=True)
    created_at = models.DateTimeField("criada em", auto_now_add=True)

    class Meta:
        verbose_name = "vínculo com escritório"
        verbose_name_plural = "vínculos com escritórios"
        constraints = [
            models.UniqueConstraint(
                fields=("office", "user"),
                name="unique_office_membership_per_user",
            ),
        ]
        indexes = [
            models.Index(
                fields=("user", "is_active"),
                name="organizatio_user_id_20db6c_idx",
            )
        ]

    def __str__(self) -> str:
        return f"{self.user} — {self.office}"


class ClientCompany(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "active", "Ativa"
        PAUSED = "paused", "Pausada"
        ARCHIVED = "archived", "Arquivada"

    office = models.ForeignKey(
        AccountingOffice,
        on_delete=models.PROTECT,
        related_name="companies",
    )
    legal_name = models.CharField("razão social", max_length=255)
    tax_identifier = models.CharField(
        "CNPJ",
        max_length=14,
        validators=[validate_tax_identifier],
    )
    state_registration = models.CharField(
        "inscrição estadual",
        max_length=32,
        blank=True,
    )
    state = models.CharField("UF", max_length=2, default="PB")
    status = models.CharField(
        "situação",
        max_length=16,
        choices=Status,
        default=Status.ACTIVE,
    )
    created_at = models.DateTimeField("criado em", auto_now_add=True)
    updated_at = models.DateTimeField("atualizado em", auto_now=True)

    class Meta:
        verbose_name = "empresa cliente"
        verbose_name_plural = "empresas clientes"
        constraints = [
            models.UniqueConstraint(
                fields=("office", "tax_identifier"),
                name="unique_company_tax_identifier_per_office",
            ),
        ]
        indexes = [models.Index(fields=("office", "status"))]

    def __str__(self) -> str:
        return f"{self.legal_name} ({self.tax_identifier})"

    def clean(self) -> None:
        super().clean()
        self.tax_identifier = normalize_tax_identifier(self.tax_identifier)
