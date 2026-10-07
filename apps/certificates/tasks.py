from celery import shared_task

from apps.certificates.services.uploads import (
    expire_staged_certificate_uploads,
    process_certificate_upload,
)


@shared_task
def process_staged_certificate_upload(upload_id: int) -> str:
    return process_certificate_upload(upload_id)


@shared_task
def expire_staged_certificate_uploads_task() -> int:
    return expire_staged_certificate_uploads()
