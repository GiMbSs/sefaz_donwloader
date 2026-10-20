"""Forms used by the accounting workstation, not by the Django Admin."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from django import forms
from django.core.files.uploadedfile import UploadedFile
from django.db.models import QuerySet

from apps.certificates.services.uploads import (
    CertificateUploadError,
    validate_certificate_upload_metadata,
)
from apps.organizations.models import AccountingOffice, ClientCompany
from apps.organizations.validators import normalize_tax_identifier

WEEKDAY_CHOICES = (
    ("0", "Segunda"),
    ("1", "Terça"),
    ("2", "Quarta"),
    ("3", "Quinta"),
    ("4", "Sexta"),
    ("5", "Sábado"),
    ("6", "Domingo"),
)


if TYPE_CHECKING:
    ModelFormBase = forms.ModelForm[Any]
else:
    ModelFormBase = forms.ModelForm


class AccountingOfficeForm(ModelFormBase):
    """Initial tenant registration, limited to the installation administrator."""

    tax_identifier = forms.CharField(
        label="CNPJ do escritório",
        max_length=18,
        widget=forms.TextInput(attrs={"inputmode": "text", "maxlength": 18}),
    )

    class Meta:
        model = AccountingOffice
        fields = ("legal_name", "tax_identifier")
        widgets = {
            "legal_name": forms.TextInput(attrs={"autocomplete": "organization"}),
        }

    def clean_tax_identifier(self) -> str:
        return normalize_tax_identifier(self.cleaned_data["tax_identifier"])


class ClientCompanyForm(ModelFormBase):
    tax_identifier = forms.CharField(
        label="CNPJ",
        max_length=18,
        widget=forms.TextInput(
            attrs={"inputmode": "text", "maxlength": 18},
        ),
    )

    class Meta:
        model = ClientCompany
        labels = {"office": "Escritório contábil"}
        fields = (
            "office",
            "legal_name",
            "tax_identifier",
            "state_registration",
            "state",
            "status",
        )
        widgets = {
            "legal_name": forms.TextInput(attrs={"autocomplete": "organization"}),
            "tax_identifier": forms.TextInput(attrs={"inputmode": "text"}),
            "state_registration": forms.TextInput(attrs={"autocomplete": "off"}),
            "state": forms.TextInput(
                attrs={"maxlength": 2, "autocomplete": "address-level1"}
            ),
        }

    def __init__(
        self,
        *args: Any,
        offices: QuerySet[AccountingOffice] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        cast(
            "forms.ModelChoiceField[AccountingOffice]", self.fields["office"]
        ).queryset = offices if offices is not None else AccountingOffice.objects.none()
        cast(forms.TypedChoiceField, self.fields["status"]).choices = (
            (ClientCompany.Status.ACTIVE, ClientCompany.Status.ACTIVE.label),
            (ClientCompany.Status.INACTIVE, ClientCompany.Status.INACTIVE.label),
        )

    def clean_tax_identifier(self) -> str:
        return normalize_tax_identifier(self.cleaned_data["tax_identifier"])

    def clean_state(self) -> str:
        return str(self.cleaned_data["state"]).strip().upper()


class ClientCompanyCreateForm(ClientCompanyForm):
    certificate_file = forms.FileField(
        label="Certificado A1 (opcional)",
        required=False,
        help_text="Arquivo .pfx ou .p12 de até 5 MB; a validação ocorre após o envio.",
        widget=forms.ClearableFileInput(
            attrs={"accept": ".pfx,.p12,application/x-pkcs12"}
        ),
    )
    certificate_password = forms.CharField(
        label="Senha do certificado",
        max_length=1024,
        required=False,
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
    )

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.order_fields(
            (
                "office",
                "legal_name",
                "tax_identifier",
                "state_registration",
                "state",
                "status",
                "certificate_file",
                "certificate_password",
            )
        )

    def clean_certificate_file(self) -> UploadedFile | None:
        certificate_file = cast(
            UploadedFile | None, self.cleaned_data.get("certificate_file")
        )
        if certificate_file is None:
            return None
        try:
            validate_certificate_upload_metadata(
                filename=certificate_file.name or "",
                payload_size=certificate_file.size or 0,
                password="valid-for-size-check",
            )
        except CertificateUploadError as error:
            raise forms.ValidationError(str(error)) from error
        return certificate_file

    def clean(self) -> dict[str, object]:
        cleaned_data = super().clean() or {}
        certificate_file = cleaned_data.get("certificate_file")
        password = cleaned_data.get("certificate_password")
        if bool(certificate_file) != bool(password):
            message = "Informe o arquivo e a senha do certificado juntos."
            if certificate_file:
                self.add_error("certificate_password", message)
            else:
                self.add_error("certificate_file", message)
        return cleaned_data


class CompanyArchiveForm(forms.Form):
    confirmation_tax_identifier = forms.CharField(
        label="Confirme o CNPJ da empresa",
        max_length=18,
        widget=forms.TextInput(attrs={"autocomplete": "off"}),
    )
    understand_retention = forms.BooleanField(
        label=(
            "Entendo que a exclusão arquiva o cadastro e preserva arquivos e "
            "evidências fiscais pelo prazo de retenção."
        ),
        required=True,
    )

    def __init__(self, *args: Any, company: ClientCompany, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.company = company

    def clean_confirmation_tax_identifier(self) -> str:
        value = normalize_tax_identifier(
            self.cleaned_data["confirmation_tax_identifier"]
        )
        if value != self.company.tax_identifier:
            raise forms.ValidationError("O CNPJ informado não corresponde à empresa.")
        return value


class AlertResolutionForm(forms.Form):
    resolution_note = forms.CharField(
        label="Registro da resolução",
        max_length=2000,
        required=False,
        widget=forms.Textarea(
            attrs={
                "rows": 2,
                "placeholder": "Opcional: informe a medida adotada.",
            }
        ),
    )


class CertificateUploadForm(forms.Form):
    certificate_file = forms.FileField(
        label="Arquivo do certificado A1",
        help_text="Envie um arquivo .pfx ou .p12 de até 5 MB.",
        widget=forms.ClearableFileInput(
            attrs={"accept": ".pfx,.p12,application/x-pkcs12"}
        ),
    )
    password = forms.CharField(
        label="Senha do certificado",
        max_length=1024,
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
    )

    def clean_certificate_file(self) -> UploadedFile:
        certificate_file = cast(UploadedFile, self.cleaned_data["certificate_file"])
        try:
            validate_certificate_upload_metadata(
                filename=certificate_file.name or "",
                payload_size=certificate_file.size or 0,
                password="valid-for-size-check",
            )
        except CertificateUploadError as error:
            raise forms.ValidationError(str(error)) from error
        return certificate_file
