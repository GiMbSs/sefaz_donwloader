from celery import shared_task

from apps.fiscal.services.distribution import (
    DistributionParseError,
    DistributionReprocessError,
    reprocess_distribution_batch,
)
from apps.fiscal.services.execution import execute_sync_request
from apps.fiscal.services.storage import FiscalStorageError
from apps.fiscal.services.sync import enqueue_due_synchronizations


@shared_task
def process_sync_request(sync_request_id: int) -> str:
    """Perform one DF-e consultation exclusively in the fiscal worker."""
    return execute_sync_request(sync_request_id)


@shared_task
def reprocess_distribution_batch_task(batch_id: int) -> str:
    """Rebuild one failed batch only from its archived local response."""
    try:
        return reprocess_distribution_batch(batch_id=batch_id).processing_status
    except (DistributionParseError, DistributionReprocessError, FiscalStorageError):
        return "failed"


@shared_task
def schedule_eligible_synchronizations() -> int:
    """Queue due company policies; a separate worker use case owns SEFAZ I/O."""
    return enqueue_due_synchronizations()
