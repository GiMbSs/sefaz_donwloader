from datetime import date
from uuid import uuid4

from django.utils import timezone

from apps.fiscal.atf.types import (
    AttachmentRef,
    MessageRef,
    ParsedMessage,
    Period,
    SubmissionEvidence,
)


def test_nfce_message_can_arrive_without_attachment_then_gain_multiple_attachments():
    from apps.fiscal.atf.messages import parse_message

    pending = """<body>FIS_1484 - Consulta de NFC-e por Emitente
    Período solicitado: 10/10/2024 a 10/10/2024
    Solicitação em processamento. Aguarde.
    A não existência de arquivo em anexo significa que
    não existem dados para o período consultado.</body>""".encode()
    first = parse_message(pending, "21", "20")
    assert first.ref.sender_code == "FIS_1484"
    assert first.outcome == "pending"
    ready = pending.replace(
        b"</body>",
        b'<a href="javascript:mostrarArquivo(0)">XML</a>'
        b'<a href="javascript:mostrarArquivo(1)">XML</a></body>',
    )
    second = parse_message(ready, "21", "20")
    assert second.outcome == "success"
    assert [ref.index for ref in second.attachments] == [0, 1]


def test_nfce_correlation_never_selects_nfe_group_for_the_same_period():
    from apps.fiscal.atf.correlation import reconcile_result

    period = Period(date(2024, 10, 10), date(2024, 10, 10))
    evidence = SubmissionEvidence(uuid4(), uuid4(), (), timezone.now())
    messages = tuple(
        ParsedMessage(
            MessageRef(str(i), str(i), sender, "", True),
            period,
            (AttachmentRef(str(i), 0),),
            "success",
        )
        for i, sender in [(1, "FIS_1322"), (2, "FIS_1484")]
    )
    result = reconcile_result(evidence, messages, period=period, document_model="65")
    assert result.outcome == "matched"
    assert result.candidates == ("2",)


def test_nfce_group_with_pending_child_is_not_finished_early():
    from apps.fiscal.atf.correlation import reconcile_result

    period = Period(date(2024, 10, 10), date(2024, 10, 10))
    evidence = SubmissionEvidence(uuid4(), uuid4(), (), timezone.now())
    messages = (
        ParsedMessage(
            MessageRef("21", "20", "FIS_1484", "", True),
            period,
            (AttachmentRef("21", 0),),
            "success",
        ),
        ParsedMessage(
            MessageRef("22", "20", "FIS_1484", "", False),
            period,
            (),
            "pending",
            {"processing": "true"},
        ),
    )
    result = reconcile_result(evidence, messages, period=period, document_model="65")
    assert result.outcome == "pending"


def test_initial_notification_does_not_block_completed_nfce_result():
    from apps.fiscal.atf.correlation import reconcile_result

    period = Period(date(2024, 10, 10), date(2024, 10, 10))
    evidence = SubmissionEvidence(uuid4(), uuid4(), (), timezone.now())
    messages = (
        ParsedMessage(
            MessageRef("21", "20", "FIS_1484", "", False), None, (), "pending"
        ),
        ParsedMessage(
            MessageRef("22", "20", "FIS_1484", "", True),
            period,
            (AttachmentRef("22", 0),),
            "success",
        ),
    )
    assert (
        reconcile_result(evidence, messages, period=period, document_model="65").outcome
        == "matched"
    )


def test_ready_result_and_another_pending_candidate_are_ambiguous():
    from apps.fiscal.atf.correlation import reconcile_result

    period = Period(date(2024, 10, 10), date(2024, 10, 10))
    evidence = SubmissionEvidence(uuid4(), uuid4(), (), timezone.now())
    messages = (
        ParsedMessage(
            MessageRef("21", "20", "FIS_1484", "", True),
            period,
            (AttachmentRef("21", 0),),
            "success",
        ),
        ParsedMessage(
            MessageRef("31", "30", "FIS_1484", "", False),
            period,
            (),
            "pending",
            {"processing": "true"},
        ),
    )
    assert (
        reconcile_result(evidence, messages, period=period, document_model="65").outcome
        == "ambiguous"
    )


def test_pending_result_with_generic_footer_blocks_until_its_attachment_arrives():
    from apps.fiscal.atf.correlation import reconcile_result
    from apps.fiscal.atf.messages import parse_message

    period = Period(date(2024, 10, 10), date(2024, 10, 10))
    evidence = SubmissionEvidence(uuid4(), uuid4(), (), timezone.now())
    pending = parse_message(
        """<body>FIS_1484 Período solicitado: 10/10/2024 a 10/10/2024
        A não existência de arquivo em anexo significa que não existem dados
        para o período consultado.</body>""".encode(),
        "22",
        "20",
    )
    ready = ParsedMessage(
        MessageRef("21", "20", "FIS_1484", "", True),
        period,
        (AttachmentRef("21", 0),),
        "success",
    )
    result = reconcile_result(
        evidence, (ready, pending), period=period, document_model="65"
    )
    assert result.outcome == "pending"
