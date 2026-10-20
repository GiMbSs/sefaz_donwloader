from celery import shared_task

from apps.certificates.services.uploads import (
    expire_staged_certificate_uploads,
    process_certificate_upload,
    retry_submitted_certificate_uploads,
)


@shared_task
def process_staged_certificate_upload(upload_id: int) -> str:
    return process_certificate_upload(upload_id)


@shared_task
def expire_staged_certificate_uploads_task() -> int:
    expired = expire_staged_certificate_uploads()
    retry_submitted_certificate_uploads()
    return expired
