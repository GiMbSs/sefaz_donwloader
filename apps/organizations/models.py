from django.core.exceptions import ValidationError
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

    def clean_fields(self, exclude=None) -> None:
        if isinstance(self.tax_identifier, str):
            self.tax_identifier = normalize_tax_identifier(self.tax_identifier)
        super().clean_fields(exclude=exclude)

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
        INACTIVE = "inactive", "Inativa"
        ARCHIVED = "archived", "Arquivada"

    class FiscalEnvironment(models.TextChoices):
        PRODUCTION = "production", "Produção"
        HOMOLOGATION = "homologation", "Homologação"

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
    fiscal_environment = models.CharField(
        "ambiente fiscal",
        max_length=16,
        choices=FiscalEnvironment,
        default=FiscalEnvironment.HOMOLOGATION,
    )
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
        indexes = [
            models.Index(
                fields=("office", "status"),
                name="organizatio_office__26c3f5_idx",
            )
        ]

    def __str__(self) -> str:
        return f"{self.legal_name} ({self.tax_identifier})"

    def clean_fields(self, exclude=None) -> None:
        if isinstance(self.tax_identifier, str):
            self.tax_identifier = normalize_tax_identifier(self.tax_identifier)
        super().clean_fields(exclude=exclude)

    def clean(self) -> None:
        super().clean()
        self.tax_identifier = normalize_tax_identifier(self.tax_identifier)
        if self.pk is None:
            return
        previous_environment = (
            type(self)
            .objects.filter(pk=self.pk)
            .values_list("fiscal_environment", flat=True)
            .first()
        )
        if (
            previous_environment
            and previous_environment != self.fiscal_environment
            and (
                self.nsu_controls.exists()
                or self.sync_requests.exists()
            )
        ):
            raise ValidationError(
                {
                    "fiscal_environment": (
                        "O ambiente não pode ser alterado após iniciar o histórico "
                        "fiscal. Cadastre uma empresa de teste separada."
                    )
                }
            )
