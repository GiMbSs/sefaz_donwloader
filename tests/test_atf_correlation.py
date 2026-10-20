from datetime import date
from uuid import uuid4

from django.utils import timezone


def test_same_period_in_multiple_new_groups_is_ambiguous():
    from apps.fiscal.atf.correlation import reconcile_result
    from apps.fiscal.atf.types import (
        MessageRef,
        ParsedMessage,
        Period,
        SubmissionEvidence,
    )

    period = Period(date(2024, 1, 1), date(2024, 1, 31))
    evidence = SubmissionEvidence(uuid4(), uuid4(), ("old",), timezone.now())
    messages = tuple(
        ParsedMessage(
            MessageRef(message, parent, "FIS_1322", "", True), period, (), "success"
        )
        for message, parent in [("1", "new-a"), ("2", "new-b"), ("3", "old")]
    )
    result = reconcile_result(evidence, messages, period=period)
    assert result.outcome == "ambiguous"
    assert result.candidates == ("new-a", "new-b")


def test_correlation_ignores_other_sender_and_period():
    from apps.fiscal.atf.correlation import reconcile_result
    from apps.fiscal.atf.types import (
        MessageRef,
        ParsedMessage,
        Period,
        SubmissionEvidence,
    )

    period = Period(date(2024, 1, 1), date(2024, 1, 31))
    evidence = SubmissionEvidence(uuid4(), uuid4(), (), timezone.now())
    messages = (
        ParsedMessage(MessageRef("1", "1", "SEG_001", "", True), period, (), "success"),
        ParsedMessage(
            MessageRef("2", "2", "FIS_1322", "", True),
            Period(date(2023, 1, 1), date(2023, 1, 31)),
            (),
            "success",
        ),
    )
    assert reconcile_result(evidence, messages, period=period).outcome == "pending"
