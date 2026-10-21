from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Literal
from uuid import UUID

DownloadFormat = Literal["xml", "txt"]


@dataclass(frozen=True)
class Period:
    start: date
    end: date

    def __post_init__(self) -> None:
        if self.start > self.end:
            raise ValueError("O início deve ser anterior ou igual ao fim.")


@dataclass(frozen=True)
class IssuerIdentity:
    cnpj: str
    remote_id: str
    form_values: Mapping[str, str]


@dataclass(frozen=True)
class RemoteIdentity:
    account_key: str


@dataclass(frozen=True)
class MessageRef:
    id: str
    parent_id: str | None
    sender_code: str
    sent_at_raw: str
    has_attachment: bool
    children_count: int = 0


@dataclass(frozen=True)
class MessagePage:
    items: tuple[MessageRef, ...]
    next_page: str | None = None


@dataclass(frozen=True)
class AttachmentRef:
    message_id: str
    index: int
    filename: str | None = None


@dataclass(frozen=True)
class ParsedMessage:
    ref: MessageRef
    period: Period | None
    attachments: tuple[AttachmentRef, ...]
    outcome: str
    filters: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class SubmissionReceipt:
    accepted: bool


@dataclass(frozen=True)
class SubmissionEvidence:
    part_id: UUID
    attempt_id: UUID
    baseline_ids: tuple[str, ...]
    submitted_at: datetime
    unfiltered_group_ids: tuple[str, ...] = ()
    confirmed_group_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class CorrelationResult:
    outcome: Literal["matched", "pending", "ambiguous", "empty", "remote_failed"]
    candidates: tuple[str, ...] = ()
    confirmed_period: Period | None = None
    basis: Literal["message_filters", "manual_binding", "unfiltered_candidate"] = (
        "message_filters"
    )


@dataclass(frozen=True)
class DownloadedArchive:
    staging_path: Path
    sha256: str
    byte_count: int
    content_type: str
    filename: str | None = None
