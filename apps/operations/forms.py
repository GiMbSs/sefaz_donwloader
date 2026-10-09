"""Forms used by the accounting workstation, not by the Django Admin."""

from __future__ import annotations

from django import forms
from django.core.files.uploadedfile import UploadedFile
from django.db.models import QuerySet

from apps.certificates.services.uploads import (
    CertificateUploadError,
    validate_certificate_upload_metadata,
)
from apps.fiscal.models import SyncPolicy
from apps.fiscal.services.sync import normalize_initial_nsu
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


class AccountingOfficeForm(forms.ModelForm):
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


class ClientCompanyForm(forms.ModelForm):
    tax_identifier = forms.CharField(
        label="CNPJ",
        max_length=18,
        widget=forms.TextInput(
            attrs={"inputmode": "text", "maxlength": 18},
        ),
    )

    class Meta:
        model = ClientCompany
        fields = (
            "office",
            "legal_name",
            "tax_identifier",
            "state_registration",
            "state",
            "fiscal_environment",
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
        *args,
        offices: QuerySet[AccountingOffice] | None = None,
        **kwargs,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.fields["office"].queryset = (
            offices if offices is not None else AccountingOffice.objects.none()
        )
        self.fields["status"].choices = (
            (ClientCompany.Status.ACTIVE, ClientCompany.Status.ACTIVE.label),
            (ClientCompany.Status.INACTIVE, ClientCompany.Status.INACTIVE.label),
        )

    def clean_tax_identifier(self) -> str:
        return normalize_tax_identifier(self.cleaned_data["tax_identifier"])

    def clean_state(self) -> str:
        return self.cleaned_data["state"].strip().upper()


class ClientCompanyCreateForm(ClientCompanyForm):
    initial_nsu = forms.CharField(
        label="NSU inicial (opcional)",
        max_length=15,
        required=False,
        help_text=(
            "Último NSU já processado pela contabilidade. O próximo pedido "
            "buscará somente a sequência posterior e este valor não poderá ser "
            "alterado depois."
        ),
        widget=forms.TextInput(
            attrs={"inputmode": "numeric", "maxlength": 15, "autocomplete": "off"}
        ),
    )
    certificate_file = forms.FileField(
        label="Certificado A1 (opcional)",
        required=False,
        help_text="Arquivo .pfx ou .p12 de até 5 MB; será validado pelo worker.",
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

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.order_fields(
            (
                "office",
                "legal_name",
                "tax_identifier",
                "state_registration",
                "state",
                "fiscal_environment",
                "initial_nsu",
                "status",
                "certificate_file",
                "certificate_password",
            )
        )

    def clean_initial_nsu(self) -> str:
        value = self.cleaned_data["initial_nsu"]
        if not value:
            return ""
        try:
            return normalize_initial_nsu(value)
        except ValueError as error:
            raise forms.ValidationError(str(error)) from error

    def clean_certificate_file(self) -> UploadedFile | None:
        certificate_file = self.cleaned_data.get("certificate_file")
        if certificate_file is None:
            return None
        try:
            validate_certificate_upload_metadata(
                filename=certificate_file.name,
                payload_size=certificate_file.size,
                password="valid-for-size-check",
            )
        except CertificateUploadError as error:
            raise forms.ValidationError(str(error)) from error
        return certificate_file

    def clean(self) -> dict[str, object]:
        cleaned_data = super().clean()
        certificate_file = cleaned_data.get("certificate_file")
        password = cleaned_data.get("certificate_password")
        if bool(certificate_file) != bool(password):
            message = "Informe o arquivo e a senha do certificado juntos."
            if certificate_file:
                self.add_error("certificate_password", message)
            else:
                self.add_error("certificate_file", message)
        return cleaned_data


class SyncPolicyForm(forms.ModelForm):
    weekdays = forms.MultipleChoiceField(
        label="Dias ativos",
        choices=WEEKDAY_CHOICES,
        required=False,
        widget=forms.CheckboxSelectMultiple,
        help_text="Sem seleção significa todos os dias.",
    )

    class Meta:
        model = SyncPolicy
        fields = (
            "mode",
            "frequency",
            "scheduled_time",
            "timezone",
            "weekdays",
            "monthday",
            "is_active",
        )
        widgets = {
            "scheduled_time": forms.TimeInput(attrs={"type": "time"}),
            "timezone": forms.TextInput(attrs={"autocomplete": "off"}),
        }

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.fields["weekdays"].initial = [str(day) for day in self.instance.weekdays]

    def clean_weekdays(self) -> list[int]:
        return [int(day) for day in self.cleaned_data["weekdays"]]


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

    def __init__(self, *args, company: ClientCompany, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.company = company

    def clean_confirmation_tax_identifier(self) -> str:
        value = normalize_tax_identifier(
            self.cleaned_data["confirmation_tax_identifier"]
        )
        if value != self.company.tax_identifier:
            raise forms.ValidationError("O CNPJ informado não corresponde à empresa.")
        return value


class InitialNsuForm(forms.Form):
    initial_nsu = forms.CharField(
        label="Último NSU já processado",
        max_length=15,
        help_text=(
            "Informe o último NSU concluído no sistema anterior. O próximo "
            "pedido consultará somente os NSUs posteriores."
        ),
        widget=forms.TextInput(
            attrs={"inputmode": "numeric", "maxlength": 15, "autocomplete": "off"}
        ),
    )
    confirmation_tax_identifier = forms.CharField(
        label="Confirme o CNPJ da empresa",
        max_length=18,
        widget=forms.TextInput(attrs={"autocomplete": "off"}),
    )
    understand_immutable = forms.BooleanField(
        label=(
            "Entendo que esse NSU inicial será usado uma única vez e não poderá "
            "ser alterado depois da primeira solicitação."
        ),
        required=True,
    )

    def __init__(self, *args, company: ClientCompany, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.company = company

    def clean_initial_nsu(self) -> str:
        try:
            return normalize_initial_nsu(self.cleaned_data["initial_nsu"])
        except ValueError as error:
            raise forms.ValidationError(str(error)) from error

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
        certificate_file = self.cleaned_data["certificate_file"]
        try:
            validate_certificate_upload_metadata(
                filename=certificate_file.name,
                payload_size=certificate_file.size,
                password="valid-for-size-check",
            )
        except CertificateUploadError as error:
            raise forms.ValidationError(str(error)) from error
        return certificate_file
