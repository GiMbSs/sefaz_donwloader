from celery import shared_task


@shared_task(acks_late=True, reject_on_worker_lost=True)
def process_download_part(part_id: str) -> str:
    from apps.fiscal.services.downloads import advance_part

    return advance_part(part_id).status


@shared_task(acks_late=True, reject_on_worker_lost=True)
def poll_download_part(part_id: str) -> str:
    from apps.fiscal.services.downloads import advance_part

    return advance_part(part_id).status


@shared_task
def revalidate_download_archive(archive_id: str) -> str:
    from apps.fiscal.services.documents import index_archive

    index_archive(archive_id)
    return "succeeded"


@shared_task
def schedule_due_downloads() -> int:
    from django.utils import timezone

    from apps.fiscal.services.scheduling import enqueue_due_downloads

    return enqueue_due_downloads(now=timezone.now())
