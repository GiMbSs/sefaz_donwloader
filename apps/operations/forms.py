"""Forms used by the accounting workstation, not by the Django Admin."""

from __future__ import annotations

from django import forms
from django.core.files.uploadedfile import UploadedFile
from django.db.models import QuerySet

from apps.certificates.services.uploads import (
    CertificateUploadError,
    validate_certificate_upload_metadata,
)
from apps.fiscal.models import NsuControl, SyncPolicy
from apps.organizations.models import AccountingOffice, ClientCompany


WEEKDAY_CHOICES = (
    ("0", "Segunda"),
    ("1", "Terça"),
    ("2", "Quarta"),
    ("3", "Quinta"),
    ("4", "Sexta"),
    ("5", "Sábado"),
    ("6", "Domingo"),
)


class ClientCompanyForm(forms.ModelForm):
    class Meta:
        model = ClientCompany
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
        *args,
        offices: QuerySet[AccountingOffice] | None = None,
        **kwargs,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.fields["office"].queryset = (
            offices if offices is not None else AccountingOffice.objects.none()
        )

    def clean_state(self) -> str:
        return self.cleaned_data["state"].strip().upper()


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
        fields = ("mode", "scheduled_time", "timezone", "weekdays", "is_active")
        widgets = {
            "scheduled_time": forms.TimeInput(attrs={"type": "time"}),
            "timezone": forms.TextInput(attrs={"autocomplete": "off"}),
        }

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.fields["weekdays"].initial = [str(day) for day in self.instance.weekdays]

    def clean_weekdays(self) -> list[int]:
        return [int(day) for day in self.cleaned_data["weekdays"]]


class ManualSyncRequestForm(forms.Form):
    environment = forms.ChoiceField(
        label="Ambiente",
        choices=NsuControl.Environment.choices,
        initial=NsuControl.Environment.PRODUCTION,
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
