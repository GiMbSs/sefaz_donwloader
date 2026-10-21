from typing import Literal

from .profiles import document_profile
from .types import CorrelationResult, ParsedMessage, Period, SubmissionEvidence


def reconcile_result(
    evidence: SubmissionEvidence,
    messages: tuple[ParsedMessage, ...],
    *,
    period: Period,
    document_model: str = "55",
) -> CorrelationResult:
    groups: dict[str, set[str]] = {}
    processing_groups: set[str] = set()
    sender = document_profile(document_model).sender_code
    baseline = set(evidence.baseline_ids)
    unfiltered = set(evidence.unfiltered_group_ids)
    confirmed = set(evidence.confirmed_group_ids)
    for message in messages:
        group = message.ref.parent_id or message.ref.id
        if (
            group not in baseline
            and message.ref.sender_code == sender
            and (
                (message.outcome == "pending" and message.period == period)
                or (
                    message.filters.get("processing") == "true"
                    and message.period in {None, period}
                )
            )
        ):
            processing_groups.add(group)
        if (
            group in baseline
            or message.ref.sender_code != sender
            or (
                message.period != period
                and not (
                    message.period is None
                    and (
                        group in confirmed
                        or (
                            group in unfiltered
                            and message.outcome in {"empty", "remote_failed"}
                        )
                    )
                )
            )
        ):
            continue
        groups.setdefault(group, set()).add(message.outcome)
    candidates = tuple(sorted(groups))
    if len(candidates) > 1:
        return CorrelationResult("ambiguous", candidates, period)
    if not candidates:
        return CorrelationResult("pending")
    outcomes = groups[candidates[0]]
    # Earlier notifications remain in the mailbox after a ZIP becomes ready.
    # A visible attachment in this group can be delivered without waiting for
    # those historical messages to change.
    if candidates[0] in processing_groups and not outcomes.intersection(
        {"success", "empty", "remote_failed"}
    ):
        return CorrelationResult("pending", candidates, period)
    if len(outcomes) > 1:
        outcomes.discard("pending")
    if len(outcomes) > 1:
        return CorrelationResult("ambiguous", candidates, period)
    outcome = next(iter(outcomes))
    has_filters = any(
        message.period == period
        and (message.ref.parent_id or message.ref.id) == candidates[0]
        and message.outcome == outcome
        for message in messages
    )
    basis: Literal["message_filters", "manual_binding"]
    if candidates[0] in confirmed:
        basis = "manual_binding"
    elif not has_filters:
        return CorrelationResult(
            "ambiguous", candidates, period, "unfiltered_candidate"
        )
    else:
        basis = "message_filters"
    if outcome == "success":
        return CorrelationResult("matched", candidates, period)
    if outcome == "empty":
        return CorrelationResult("empty", candidates, period, basis)
    if outcome == "remote_failed":
        return CorrelationResult("remote_failed", candidates, period, basis)
    return CorrelationResult("pending", candidates, period)
