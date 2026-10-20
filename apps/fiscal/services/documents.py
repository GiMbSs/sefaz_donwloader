"""Index invoice versions, events and original reports independently."""

import zipfile
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from django.db import transaction

from apps.fiscal.atf.errors import AtfArtifactError
from apps.fiscal.atf.types import DownloadedArchive, Period
from apps.fiscal.models import (
    ArchiveMember,
    DownloadArchive,
    FiscalEvent,
    InvoiceDocument,
    InvoiceXmlVersion,
)

from .artifacts import _member_name, validate_archive
from .storage import FiscalStorage


@dataclass(frozen=True)
class IndexResult:
    invoice_count: int
    event_count: int
    txt_count: int
    warnings: tuple[str, ...]


def index_archive(archive_id: Any, *, heartbeat: Any = None) -> IndexResult:
    archive = DownloadArchive.objects.select_related("part__request__company").get(
        pk=archive_id
    )
    part = archive.part
    storage = FiscalStorage()
    original = storage.path_for_read(archive.path)
    download = DownloadedArchive(
        original, archive.sha256, archive.byte_count, "application/zip"
    )
    validation = validate_archive(
        download,
        company_id=part.request.company_id,
        period=Period(part.start_date, part.end_date),
        format=part.format,
        document_model=part.request.document_model,
        heartbeat=heartbeat,
    )
    counts = {"invoice": 0, "event": 0, "txt": 0}
    with zipfile.ZipFile(original) as source:
        original_names = {
            _member_name(info.filename): info for info in source.infolist()
        }
        for member in validation.members:
            if heartbeat:
                heartbeat()
            data = source.read(original_names[member.name])
            if len(data) != member.byte_count:
                raise AtfArtifactError("atf_member_changed")
            relative = (
                Path(archive.path).parent
                / "membros"
                / (member.sha256 + (".txt" if member.kind == "txt" else ".xml"))
            )
            storage._write(relative, data)
            with transaction.atomic():
                version, event = None, None
                meta = member.metadata
                if member.kind == "invoice":
                    invoice, _ = InvoiceDocument.objects.get_or_create(
                        company_id=part.request.company_id,
                        access_key=meta["access_key"],
                        defaults={
                            "issued_on": date.fromisoformat(meta["issued_on"]),
                            "model": meta["model"],
                            "number": int(meta["number"]),
                        },
                    )
                    if invoice.number is None:
                        invoice.number = int(meta["number"])
                        invoice.save(update_fields=["number", "last_received_at"])
                    version, _ = InvoiceXmlVersion.objects.get_or_create(
                        document=invoice,
                        sha256=member.sha256,
                        defaults={
                            "path": relative.as_posix(),
                            "validation_status": meta["validation_status"],
                        },
                    )
                elif member.kind == "event":
                    event, _ = FiscalEvent.objects.get_or_create(
                        company_id=part.request.company_id,
                        access_key=meta["access_key"],
                        event_type=meta["event_type"],
                        sequence=int(meta["sequence"]),
                        sha256=member.sha256,
                        defaults={
                            "path": relative.as_posix(),
                            "validation_status": meta["validation_status"],
                        },
                    )
                ArchiveMember.objects.get_or_create(
                    archive=archive,
                    name=member.name,
                    defaults={
                        "kind": member.kind,
                        "sha256": member.sha256,
                        "byte_count": member.byte_count,
                        "path": relative.as_posix(),
                        "invoice_version": version,
                        "event": event,
                    },
                )
            counts[member.kind] += 1
    return IndexResult(
        counts["invoice"], counts["event"], counts["txt"], validation.warnings
    )
