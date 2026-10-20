from typing import Any, cast

from django import forms
from django.utils import timezone

from apps.fiscal.atf.profiles import DOCUMENT_CHOICES
from apps.fiscal.models import DownloadPolicy

from .forms import WEEKDAY_CHOICES, ModelFormBase


class DownloadRequestForm(forms.Form):
    document_model = forms.ChoiceField(
        label="Tipo de documento", choices=DOCUMENT_CHOICES, initial="55"
    )
    start_date = forms.DateField(
        label="Data inicial", widget=forms.DateInput(attrs={"type": "date"})
    )
    end_date = forms.DateField(
        label="Data final", widget=forms.DateInput(attrs={"type": "date"})
    )
    formats = forms.MultipleChoiceField(
        label="Arquivos desejados",
        choices=[("xml", "XML das notas e eventos"), ("txt", "Relatório TXT")],
        initial=["xml", "txt"],
        widget=forms.CheckboxSelectMultiple,
    )
    repeat = forms.BooleanField(
        label="Solicitar novamente se este período já foi consultado",
        required=False,
        help_text="Cria uma nova coleta; os arquivos anteriores serão preservados.",
    )

    def clean(self) -> Any:
        data = super().clean() or {}
        start, end = data.get("start_date"), data.get("end_date")
        if start and end and start > end:
            self.add_error(
                "end_date", "A data final deve ser igual ou posterior à inicial."
            )
        if end and end > timezone.localdate():
            self.add_error("end_date", "Escolha uma data até hoje.")
        return data


class DownloadPolicyForm(ModelFormBase):
    document_models = forms.MultipleChoiceField(
        label="Documentos do download automático",
        choices=DOCUMENT_CHOICES,
        widget=forms.CheckboxSelectMultiple,
    )
    weekdays = forms.MultipleChoiceField(
        label="Dias da semana",
        choices=WEEKDAY_CHOICES,
        required=False,
        widget=forms.CheckboxSelectMultiple,
    )
    formats = forms.MultipleChoiceField(
        label="Formatos do download automático",
        choices=[("xml", "XML"), ("txt", "TXT")],
        widget=forms.CheckboxSelectMultiple,
    )

    class Meta:
        model = DownloadPolicy
        fields = (
            "mode",
            "frequency",
            "scheduled_time",
            "timezone",
            "weekdays",
            "monthday",
            "period_strategy",
            "rolling_days",
            "formats",
            "document_models",
            "is_active",
        )
        labels = {
            "mode": "Modo de operação",
            "frequency": "Frequência",
            "scheduled_time": "Horário",
            "timezone": "Fuso horário",
            "monthday": "Dia do mês",
            "period_strategy": "Período a consultar",
            "rolling_days": "Quantidade de dias completos",
            "is_active": "Agendamento ativo",
        }
        widgets = {
            "scheduled_time": forms.TimeInput(format="%H:%M", attrs={"type": "time"})
        }

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.fields["weekdays"].initial = [str(day) for day in self.instance.weekdays]
        self.fields["formats"].initial = self.instance.formats
        self.fields["document_models"].initial = self.instance.document_models

    def clean_weekdays(self) -> Any:
        return [int(day) for day in self.cleaned_data["weekdays"]]


class RemoteResultResolutionForm(forms.Form):
    candidate = forms.ChoiceField(label="Resultado a conferir", required=False)
    note = forms.CharField(
        label="Motivo da decisão",
        max_length=2000,
        widget=forms.Textarea(attrs={"rows": 3}),
    )
    abandon = forms.BooleanField(
        label="Encerrar localmente a tentativa incerta", required=False
    )
    acknowledge = forms.BooleanField(
        label="Entendo que o pedido pode continuar existindo na SEFAZ-PB",
        required=False,
    )

    def __init__(self, *args: Any, candidates: Any = (), **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        cast(forms.ChoiceField, self.fields["candidate"]).choices = [
            ("", "Selecione um resultado")
        ] + [(value, f"Consulta {value}") for value in candidates]

    def clean(self) -> Any:
        data = super().clean() or {}
        if bool(data.get("candidate")) == bool(data.get("abandon")):
            raise forms.ValidationError(
                "Escolha um resultado ou encerre a tentativa, uma ação por vez."
            )
        if data.get("abandon") and not data.get("acknowledge"):
            self.add_error("acknowledge", "Confirme a situação do pedido remoto.")
        return data
