from celery import shared_task


@shared_task
def schedule_eligible_synchronizations() -> int:
    """Placeholder for phase-three scheduling without contacting SEFAZ.

    The future implementation must query persisted policies and create
    idempotent SyncRequest records. It must not make a fiscal request here.
    """
    return 0

