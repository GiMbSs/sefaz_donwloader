from typing import Any

from django import template

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
    return {
        "atf_identity_mismatch": "O resultado não corresponde à empresa solicitada.",
        "atf_submission_uncertain": (
            "O envio não foi confirmado. O sistema verifica a caixa de mensagens "
            "antes de prosseguir."
        ),
        "atf_result_ambiguous": (
            "Há mais de um resultado possível. Solicite a conferência do administrador."
        ),
        "atf_authentication_failed": (
            "Não foi possível autenticar. Verifique o certificado A1."
        ),
        "atf_portal_changed": (
            "A página da SEFAZ-PB mudou e precisa de ajuste na integração."
        ),
        "atf_artifact_rejected": "O arquivo recebido não passou pela conferência.",
        "atf_wait_timeout": (
            "A espera pelo resultado terminou. Você pode retomar a verificação."
        ),
    }.get(
        value,
        "Não foi possível concluir esta etapa. Revise os alertas antes de retomar.",
    )
