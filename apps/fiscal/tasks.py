from celery import shared_task

from apps.fiscal.services.sync import enqueue_due_synchronizations


@shared_task
def schedule_eligible_synchronizations() -> int:
    """Queue due company policies; a separate worker use case owns SEFAZ I/O."""
    return enqueue_due_synchronizations()
