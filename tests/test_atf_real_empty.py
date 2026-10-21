from dataclasses import replace
from datetime import date
from uuid import uuid4

import pytest
from django.utils import timezone

from apps.fiscal.atf.correlation import reconcile_result
from apps.fiscal.atf.forms import portal_document, visible_text
from apps.fiscal.atf.messages import parse_message
from apps.fiscal.atf.types import Period, SubmissionEvidence


def test_portal_utf8_declaration_with_real_windows1252_bytes():
    content = (
        '<meta http-equiv="Content-Type" content="text/html; charset=utf-8">'
        "<body>O resultado será enviado para sua caixa de mensagens do ATF</body>"
    ).encode("cp1252")
    assert "resultado será enviado" in visible_text(portal_document(content))


@pytest.mark.parametrize("sender", ["FIS_1322", "FIS_1484"])
def test_explicit_no_records_is_empty_even_when_wrapped_as_method_error(sender):
    content = (
        f"<body>De: {sender} Enviada: 21/10/2026 17:04:48 "
        "Erro durante a execução do método: NFEletronica.gerarTxtXml. "
        "Mensagem: Nenhum registro satisfaz a pesquisa.</body>"
    ).encode()
    result = parse_message(content, "102", "100")
    assert result.outcome == "empty"
    assert result.period is None
    assert result.ref.sent_at_raw == "21/10/2026 17:04:48"


def real_group(sender, root, now):
    stamp = now.strftime("%d/%m/%Y %H:%M:%S")
    return tuple(
        parse_message(
            f"<body>De: {sender} Enviada: {stamp} {text}</body>".encode(),
            str(int(root) + index + 1),
            root,
        )
        for index, text in enumerate(
            (
                "Iniciando a execução do serviço: Consulta Genérica.",
                "Erro durante a execução do método: NFEletronica.gerarTxtXml. "
                "Mensagem: Nenhum registro satisfaz a pesquisa.",
                "Finalizando a execução do serviço: Consulta Genérica.",
            )
        )
    )


@pytest.mark.parametrize("model,sender", [("55", "FIS_1322"), ("65", "FIS_1484")])
def test_only_confirmed_submission_group_can_finish_without_filters(model, sender):
    now = timezone.now()
    evidence = SubmissionEvidence(
        uuid4(), uuid4(), (), now, confirmed_group_ids=("100",)
    )
    period = Period(date(2026, 10, 21), date(2026, 10, 21))
    messages = real_group(sender, "100", now)
    result = reconcile_result(evidence, messages, period=period, document_model=model)
    assert result.outcome == "empty"
    assert result.candidates == ("100",)
    assert result.basis == "manual_binding"
    unconfirmed = SubmissionEvidence(uuid4(), uuid4(), (), now)
    assert (
        reconcile_result(
            unconfirmed, messages, period=period, document_model=model
        ).outcome
        == "pending"
    )

    hinted = SubmissionEvidence(
        uuid4(), uuid4(), (), now, unfiltered_group_ids=("100",)
    )
    result = reconcile_result(hinted, messages, period=period, document_model=model)
    assert result.outcome == "ambiguous"
    assert result.candidates == ("100",)


def test_two_unfiltered_submission_groups_require_review():
    now = timezone.now()
    evidence = SubmissionEvidence(
        uuid4(), uuid4(), (), now, unfiltered_group_ids=("100", "200")
    )
    result = reconcile_result(
        evidence,
        real_group("FIS_1322", "100", now) + real_group("FIS_1322", "200", now),
        period=Period(date(2026, 10, 21), date(2026, 10, 21)),
    )
    assert result.outcome == "ambiguous"


def test_manual_binding_also_confirms_period_only_empty_message():
    now = timezone.now()
    period = Period(date(2026, 10, 21), date(2026, 10, 21))
    evidence = SubmissionEvidence(
        uuid4(), uuid4(), (), now, confirmed_group_ids=("100",)
    )
    messages = tuple(
        replace(message, period=period)
        for message in real_group("FIS_1322", "100", now)
    )
    result = reconcile_result(evidence, messages, period=period)
    assert result.outcome == "empty"
    assert result.basis == "manual_binding"
