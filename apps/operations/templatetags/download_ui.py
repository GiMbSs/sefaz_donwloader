from typing import Any
from uuid import UUID

from django import template
from django.urls import reverse

from apps.fiscal.atf.diagnostics import error_message

register = template.Library()


@register.filter
def download_status(value: Any) -> Any:
    return {
        "queued": "Na fila",
        "running": "Em execução",
        "waiting": "Aguardando SEFAZ-PB",
        "submitting": "Enviando consulta",
        "ambiguous": "Resultado a conferir",
        "downloading": "Baixando arquivos",
        "validating": "Conferindo arquivos",
        "succeeded": "Concluído",
        "partial": "Arquivos parcialmente disponíveis",
        "empty": "Sem notas no período",
        "failed": "Requer atenção",
        "cancelled": "Encerrado localmente",
    }.get(value, "Em acompanhamento")


@register.filter
def download_error(value: Any) -> Any:
    return error_message(str(value))


@register.filter
def download_part_status(part: Any) -> Any:
    if (
        part.status in {"waiting", "ambiguous"}
        and part.error_code == "atf_submission_uncertain"
        and not part.candidates
    ):
        return "Aguardando confirmação do envio"
    return download_status(part.status)


@register.filter
def download_request_url(value: Any) -> str:
    try:
        request_id = UUID(str(value))
    except (ValueError, TypeError, AttributeError):
        return ""
    return str(reverse("download-request-detail", args=[request_id]))


@register.filter
def download_operation(value: Any) -> str:
    return {
        "connect": "Preparação do acesso e autenticação A1",
        "submit": "Envio da consulta à SEFAZ-PB",
        "poll": "Verificação do resultado e dos arquivos",
    }.get(str(value), "Processamento do pedido")
