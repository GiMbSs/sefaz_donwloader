"""Allowlisted failure reasons shared by workers and the workstation."""

from dataclasses import dataclass

from .errors import AtfError


@dataclass(frozen=True)
class FailureDiagnostic:
    summary: str
    action: str


DIAGNOSTICS = {
    "atf_captcha_required": FailureDiagnostic(
        "A SEFAZ-PB exige validação de CAPTCHA para esta consulta.",
        "A solicitação não foi aceita pelo fluxo automático. Conclua a consulta "
        "no portal oficial com a validação exigida; retomar sem essa validação "
        "não libera o envio. Não há arquivo sendo aguardado por esta tentativa.",
    ),
    "atf_xml_issuer_mismatch": FailureDiagnostic(
        "O CNPJ do emitente no XML não corresponde à empresa solicitada.",
        "O arquivo foi rejeitado. Confira a empresa e o resultado selecionado.",
    ),
    "atf_xml_key_issuer_mismatch": FailureDiagnostic(
        "A chave da nota ou do evento no XML pertence a outro CNPJ emitente.",
        "O arquivo foi rejeitado. Solicite a conferência do resultado.",
    ),
    "atf_xml_model_mismatch": FailureDiagnostic(
        "O modelo declarado no XML não corresponde ao modelo solicitado.",
        "Confira se o pedido é de NF-e ou NFC-e antes de retomar.",
    ),
    "atf_xml_key_model_mismatch": FailureDiagnostic(
        "O modelo da chave de acesso no XML não corresponde ao pedido.",
        "O arquivo foi rejeitado. Confira se o resultado é de NF-e ou NFC-e.",
    ),
    "atf_xml_key_invalid": FailureDiagnostic(
        "O XML contém uma chave de acesso ou identificação em formato inválido.",
        "O arquivo foi rejeitado. Solicite a conferência do XML original.",
    ),
    "atf_xml_date_invalid": FailureDiagnostic(
        "O XML contém uma data ou hora de emissão inválida.",
        "O arquivo foi rejeitado. Solicite a conferência da data no XML original.",
    ),
    "atf_xml_namespace_invalid": FailureDiagnostic(
        "O XML usa um namespace não reconhecido para os dados fiscais.",
        "O arquivo foi rejeitado. Solicite a conferência da estrutura do XML.",
    ),
    "atf_txt_date_invalid": FailureDiagnostic(
        "O relatório TXT contém uma data de emissão inválida ou não reconhecida.",
        "Solicite a conferência do arquivo ao responsável pela instalação.",
    ),
    "atf_txt_issuer_mismatch": FailureDiagnostic(
        "O CNPJ do emitente no relatório TXT não corresponde à empresa solicitada.",
        "O arquivo foi rejeitado. Confira a empresa e o resultado selecionado "
        "antes de retomar; não crie uma nova consulta para substituir este pedido.",
    ),
    "atf_txt_key_issuer_mismatch": FailureDiagnostic(
        "A chave de uma nota do TXT pertence a outro CNPJ emitente.",
        "O arquivo foi rejeitado. Solicite a conferência do resultado "
        "ao administrador.",
    ),
    "atf_txt_model_mismatch": FailureDiagnostic(
        "O modelo das notas do TXT não corresponde ao modelo solicitado.",
        "Confira se o pedido é de NF-e ou NFC-e e revise o resultado selecionado.",
    ),
    "atf_txt_key_invalid": FailureDiagnostic(
        "O relatório TXT contém uma chave de acesso em formato inválido.",
        "O arquivo foi rejeitado. Solicite a conferência ao responsável "
        "pela instalação.",
    ),
    "atf_not_enabled": FailureDiagnostic(
        "A integração com a SEFAZ-PB está desativada nesta instalação.",
        "O administrador deve configurar ATF_PB_ENABLED=True, recriar os serviços "
        "web, worker e scheduler e depois retomar este pedido.",
    ),
    "atf_permission_denied": FailureDiagnostic(
        "O acesso à integração foi recusado.",
        "Verifique a ativação ATF_PB_ENABLED e a configuração do endereço da "
        "SEFAZ-PB antes de retomar. Consulte o código nos detalhes para suporte.",
    ),
    "atf_base_url_not_approved": FailureDiagnostic(
        "O endereço configurado para a SEFAZ-PB não é permitido.",
        "O administrador deve revisar ATF_PB_BASE_URL e usar o endereço oficial.",
    ),
    "atf_certificate_unavailable": FailureDiagnostic(
        "O certificado A1 da empresa não está disponível para o acesso.",
        "Confira a validação do envio do A1 e o acesso ao cofre privado e à sua "
        "chave no worker. Corrija o cadastro ou as permissões e retome o pedido.",
    ),
    "atf_certificate_expired": FailureDiagnostic(
        "O certificado A1 está fora do período de validade.",
        "Confira a data da instalação e cadastre um A1 válido antes de retomar.",
    ),
    "atf_authentication_failed": FailureDiagnostic(
        "Não foi possível autenticar na SEFAZ-PB com o certificado A1.",
        "Confira a validade e a validação do A1 desta empresa e tente retomar.",
    ),
    "atf_tls_failed": FailureDiagnostic(
        "A conexão segura com a SEFAZ-PB não pôde ser estabelecida.",
        "Confira o certificado A1, o relógio e os certificados de confiança da "
        "instalação. Não desative a verificação TLS.",
    ),
    "atf_session_expired": FailureDiagnostic(
        "A sessão na SEFAZ-PB expirou.",
        "O sistema tenta autenticar novamente e mantém a consulta já enviada.",
    ),
    "atf_transient_error": FailureDiagnostic(
        "Houve uma falha temporária na comunicação com a SEFAZ-PB.",
        "Acompanhe a próxima tentativa. Se o pedido estiver encerrado com falha, "
        "verifique a conexão da instalação e retome o acompanhamento.",
    ),
    "atf_connection_timeout": FailureDiagnostic(
        "A SEFAZ-PB não respondeu dentro do tempo de conexão ou leitura.",
        "Acompanhe a próxima tentativa; se as falhas persistirem, revise os "
        "tempos de conexão e leitura da instalação antes de retomar.",
    ),
    "atf_connection_failed": FailureDiagnostic(
        "Não foi possível estabelecer a conexão com a SEFAZ-PB.",
        "Confira internet, DNS e proxy da instalação. Acompanhe a próxima "
        "tentativa ou retome após corrigir a conexão.",
    ),
    "atf_remote_unavailable": FailureDiagnostic(
        "A SEFAZ-PB respondeu com indisponibilidade do serviço.",
        "Aguarde a próxima tentativa; o sistema preserva o pedido e seus arquivos.",
    ),
    "atf_rate_limited": FailureDiagnostic(
        "A SEFAZ-PB limitou temporariamente a frequência de acessos.",
        "Aguarde a próxima tentativa, que respeita o intervalo informado pelo portal.",
    ),
    "atf_submission_uncertain": FailureDiagnostic(
        "Não foi possível confirmar o resultado do envio à SEFAZ-PB.",
        "O sistema verifica a caixa de mensagens antes de prosseguir. Não crie "
        "outro pedido para substituir este envio incerto.",
    ),
    "atf_empty_requires_review": FailureDiagnostic(
        "A SEFAZ-PB informou ausência de notas, mas omitiu os filtros da consulta.",
        "O administrador deve usar Conferir resultado para confirmar a mensagem "
        "deste pedido. A quantidade de mensagens e o horário não comprovam "
        "sozinhos o período e o formato. Nenhuma consulta será reenviada.",
    ),
    "atf_result_ambiguous": FailureDiagnostic(
        "Não foi possível vincular o resultado com segurança a esta solicitação.",
        "O administrador deve conferir os resultados disponíveis neste pedido.",
    ),
    "atf_portal_changed": FailureDiagnostic(
        "A resposta do portal não corresponde ao formato esperado.",
        "O responsável pela instalação deve verificar a integração com o portal.",
    ),
    "atf_identity_mismatch": FailureDiagnostic(
        "O certificado ou o resultado não corresponde à empresa solicitada.",
        "Confira o CNPJ do A1 e da empresa. Os arquivos incompatíveis não são "
        "disponibilizados; solicite a conferência antes de retomar.",
    ),
    "atf_artifact_rejected": FailureDiagnostic(
        "O arquivo recebido não passou pela conferência.",
        "Confira o código de diagnóstico com o responsável pela instalação; "
        "os arquivos rejeitados não são disponibilizados.",
    ),
    "atf_wait_timeout": FailureDiagnostic(
        "O prazo de espera pelo resultado da SEFAZ-PB terminou.",
        "Retome o acompanhamento para verificar a caixa de mensagens. Pedidos "
        "agendados mantêm o reagendamento quando a política está ativa.",
    ),
    "atf_queue_unavailable": FailureDiagnostic(
        "Não foi possível enviar a etapa para a fila de processamento.",
        "O administrador deve verificar Redis e worker. O agendamento recupera "
        "etapas pendentes após a normalização.",
    ),
    "atf_company_inactive": FailureDiagnostic(
        "A empresa está inativa ou arquivada.",
        "Um administrador deve ativar a empresa antes de retomar downloads.",
    ),
    "atf_schedule_inactive": FailureDiagnostic(
        "O agendamento deste pedido está desativado.",
        "Confira o modo de operação e a ativação da política da empresa.",
    ),
    "atf_unexpected_error": FailureDiagnostic(
        "Uma falha interna interrompeu esta etapa do processamento.",
        "Informe o identificador do pedido e da tentativa ao responsável pela "
        "instalação para consultar o diagnóstico no worker antes de retomar.",
    ),
}

for _code in (
    "atf_private_tls_backend_unavailable",
    "atf_private_tls_directory_unavailable",
):
    DIAGNOSTICS[_code] = FailureDiagnostic(
        "A instalação não conseguiu preparar o acesso protegido ao certificado A1.",
        "O administrador deve conferir as permissões e o suporte TLS da instalação.",
    )
for _code in (
    "atf_html_limit",
    "atf_redirect_limit",
    "atf_missing_query_form",
    "atf_pagination_contract_unknown",
    "atf_pagination_cycle",
    "atf_message_page_limit",
    "atf_group_limit",
    "atf_candidate_limit",
):
    DIAGNOSTICS[_code] = DIAGNOSTICS["atf_portal_changed"]
for _code in (
    "atf_remote_identity_changed",
    "atf_invalid_account_namespace",
):
    DIAGNOSTICS[_code] = DIAGNOSTICS["atf_identity_mismatch"]
for _code in (
    "atf_document_model",
    "atf_invoice_scope",
    "atf_invoice_key_mismatch",
    "atf_invoice_number_mismatch",
    "atf_invoice_outside_period",
    "atf_invoice_structure",
    "atf_txt_columns",
    "atf_txt_encoding",
    "atf_txt_number_mismatch",
    "atf_txt_outside_period",
    "atf_txt_structure",
    "atf_empty_txt",
    "atf_empty_or_binary_txt",
    "atf_invalid_txt",
    "atf_invalid_xml",
    "atf_invalid_zip",
    "atf_empty_archive",
    "atf_archive_format_mismatch",
    "atf_archive_identity",
    "atf_archive_changed",
    "atf_member_changed",
    "atf_not_zip",
    "atf_missing_attachment",
    "atf_unsafe_zip_entry",
    "atf_unsafe_zip_path",
    "atf_unsupported_xml",
    "atf_zip_entry_limit",
    "atf_zip_expansion_limit",
    "atf_zip_limit",
    "atf_zip_member_limit",
    "atf_attachment_context_mismatch",
    "atf_attachment_already_bound",
    "atf_event_scope",
    "atf_event_structure",
    "atf_unrelated_message",
    "atf_validation_identity",
    "atf_invalid_size_limit",
):
    DIAGNOSTICS[_code] = DIAGNOSTICS["atf_artifact_rejected"]


def diagnostic(code: str) -> FailureDiagnostic:
    return DIAGNOSTICS.get(code, DIAGNOSTICS["atf_unexpected_error"])


def diagnostic_code(error: Exception) -> str:
    if isinstance(error, AtfError):
        reason = error.args[0] if error.args else None
        if isinstance(reason, str) and reason in DIAGNOSTICS:
            return reason
        if error.safe_code in DIAGNOSTICS:
            return error.safe_code
    return "atf_unexpected_error"


def error_message(code: str) -> str:
    detail = diagnostic(code)
    return f"{detail.summary} {detail.action}"
