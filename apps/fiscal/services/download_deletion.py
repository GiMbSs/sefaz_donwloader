"""Remove exclusive request files with persisted, retryable cleanup work."""

import logging
from typing import Any

from django.db import transaction
from django.utils import timezone

from apps.fiscal.models import (
    ArchiveMember,
    DownloadArchive,
    DownloadFileDeletion,
    DownloadPart,
    DownloadRequest,
    FiscalEvent,
    InvoiceDocument,
    InvoiceXmlVersion,
)
from apps.operations.models import AuditLog
from apps.organizations.models import ClientCompany

from .storage import FiscalStorage, FiscalStorageError
from .storage_coordination import lock_fiscal_storage

logger = logging.getLogger(__name__)


def lock_company_parts(company_id: Any) -> None:
    ClientCompany.objects.select_for_update(no_key=True).get(pk=company_id)
    list(
        DownloadPart.objects.select_for_update(of=("self",))
        .filter(request__company_id=company_id)
        .order_by("pk")
        .values_list("pk", flat=True)
    )


def prepare_file_deletion(request: DownloadRequest) -> int:
    """Caller holds the company and its parts until metadata changes commit."""
    archives = DownloadArchive.objects.filter(part__request=request)
    members = ArchiveMember.objects.filter(archive__in=archives)
    paths = set(archives.values_list("path", flat=True))
    paths.update(members.values_list("path", flat=True))
    version_ids = list(
        members.exclude(invoice_version=None).values_list(
            "invoice_version_id", flat=True
        )
    )
    event_ids = list(members.exclude(event=None).values_list("event_id", flat=True))
    document_ids = list(
        InvoiceXmlVersion.objects.filter(pk__in=version_ids).values_list(
            "document_id", flat=True
        )
    )
    archives.delete()
    versions = InvoiceXmlVersion.objects.filter(
        pk__in=version_ids, archivemember__isnull=True
    )
    events = FiscalEvent.objects.filter(pk__in=event_ids, archivemember__isnull=True)
    paths.update(versions.values_list("path", flat=True))
    paths.update(events.values_list("path", flat=True))
    versions.delete()
    events.delete()
    InvoiceDocument.objects.filter(pk__in=document_ids, versions__isnull=True).delete()
    paths.discard("")
    DownloadFileDeletion.objects.bulk_create(
        [DownloadFileDeletion(request=request, path=path) for path in sorted(paths)],
        batch_size=500,
    )
    return len(paths)


def dispatch_file_deletion(request_id: Any, *, countdown: int = 0) -> None:
    from apps.fiscal.tasks import purge_download_files

    try:
        purge_download_files.apply_async(
            args=[str(request_id)], countdown=countdown, retry=False
        )
    except Exception as error:
        logger.warning(
            "event=atf_file_cleanup_dispatch_failed request_id=%s exception_type=%s",
            request_id,
            type(error).__name__,
        )


def _referenced_paths(paths: list[str]) -> set[str]:
    references: set[str] = set()
    for model in (DownloadArchive, ArchiveMember, InvoiceXmlVersion, FiscalEvent):
        references.update(
            model.objects.filter(path__in=paths).values_list("path", flat=True)
        )
    return references


@transaction.atomic
def purge_request_files(request_id: Any) -> int:
    request = DownloadRequest.objects.get(pk=request_id)
    if request.status != "cancelled" or request.deleted_at is None:
        return 0
    lock_fiscal_storage(cleanup=True)
    # New requests cannot be created while we purge; existing publishers and
    # indexers must finish their part transactions before these locks are granted.
    lock_company_parts(request.company_id)
    jobs = list(
        request.file_deletions.select_for_update()
        .filter(completed_at=None)
        .order_by("attempts", "pk")[:500]
    )
    storage = FiscalStorage()
    removed, shared = 0, 0
    for start in range(0, len(jobs), 500):
        batch = jobs[start : start + 500]
        references = _referenced_paths([job.path for job in batch])
        for job in batch:
            job.attempts += 1
            if job.path in references:
                job.outcome = "shared"
                shared += 1
            else:
                try:
                    storage.delete(job.path)
                except (FiscalStorageError, OSError):
                    job.outcome = "storage_unavailable"
                    job.save(update_fields=["attempts", "outcome"])
                    continue
                job.outcome = "removed"
                removed += 1
            job.completed_at = timezone.now()
            job.save(update_fields=["attempts", "outcome", "completed_at"])
    if jobs:
        pending = request.file_deletions.filter(completed_at=None).count()
        AuditLog.objects.create(
            action="fiscal.download_files_purged",
            target=f"download:{request.pk}",
            payload={"removed": removed, "shared": shared, "pending": pending},
        )
        logger.info(
            "event=atf_file_cleanup request_id=%s removed=%s shared=%s pending=%s",
            request.pk,
            removed,
            shared,
            pending,
        )
    return removed
