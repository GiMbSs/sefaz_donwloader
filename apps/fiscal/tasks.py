from typing import cast
from uuid import UUID

from celery import shared_task


@shared_task(acks_late=True, reject_on_worker_lost=True)
def process_download_part(part_id: str) -> str:
    from apps.fiscal.services.downloads import advance_part

    return advance_part(part_id).status


@shared_task(acks_late=True, reject_on_worker_lost=True)
def poll_download_part(part_id: str) -> str:
    """Accept older queued task names through the current processing flow."""
    return cast(str, process_download_part(part_id))


@shared_task
def revalidate_download_archive(archive_id: str) -> str:
    from apps.fiscal.models import DownloadArchive
    from apps.fiscal.services.documents import index_archive
    from apps.fiscal.services.storage import FiscalStorageError

    if not DownloadArchive.objects.filter(pk=archive_id).exists():
        return "deleted"
    try:
        index_archive(archive_id)
    except (DownloadArchive.DoesNotExist, FileNotFoundError, FiscalStorageError):
        if not DownloadArchive.objects.filter(pk=archive_id).exists():
            return "deleted"
        raise
    return "succeeded"


@shared_task(acks_late=True, reject_on_worker_lost=True)
def purge_download_files(request_id: str | None = None) -> int:
    from django.db.models import Min

    from apps.fiscal.models import DownloadFileDeletion
    from apps.fiscal.services.download_deletion import (
        dispatch_file_deletion,
        purge_request_files,
    )

    request_ids = (
        [UUID(str(request_id))]
        if request_id
        else list(
            DownloadFileDeletion.objects.filter(completed_at=None)
            .values("request_id")
            .annotate(fewest_attempts=Min("attempts"))
            .order_by("fewest_attempts", "request_id")
            .values_list("request_id", flat=True)[:100]
        )
    )
    removed = 0
    for pk in request_ids:
        removed += purge_request_files(pk)
        if DownloadFileDeletion.objects.filter(
            request_id=pk, completed_at=None, outcome=""
        ).exists():
            dispatch_file_deletion(pk, countdown=1)
    return removed


@shared_task
def schedule_due_downloads() -> int:
    from django.utils import timezone

    from apps.fiscal.services.scheduling import enqueue_due_downloads

    return enqueue_due_downloads(now=timezone.now())
