from celery import shared_task

from apps.fiscal.services.execution import execute_sync_request
from apps.fiscal.services.sync import enqueue_due_synchronizations


@shared_task
def process_sync_request(sync_request_id: int) -> str:
    """Perform one DF-e consultation exclusively in the fiscal worker."""
    return execute_sync_request(sync_request_id)


@shared_task
def schedule_eligible_synchronizations() -> int:
    """Queue due company policies; a separate worker use case owns SEFAZ I/O."""
    return enqueue_due_synchronizations()
