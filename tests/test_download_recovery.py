from datetime import date

import pytest
from django.core.exceptions import ValidationError

from apps.fiscal.atf.types import Period


def test_recovery_preserves_uncertain_submission_without_resetting_to_queued(
    download_company, download_actor
):
    from apps.fiscal.models import DownloadAttempt, RemoteSubmissionBarrier
    from apps.fiscal.services.download_recovery import recover_download_request
    from apps.fiscal.services.downloads import request_download

    request = request_download(
        company_id=download_company.pk,
        period=Period(date(2024, 1, 1), date(2024, 1, 2)),
        formats=("xml",),
        actor_id=download_actor.pk,
        trigger="manual",
        dispatch=False,
    )
    part = request.parts.get()
    part.status = "ambiguous"
    part.save()
    attempt = DownloadAttempt.objects.create(part=part, operation="submit")
    RemoteSubmissionBarrier.objects.create(
        scope="account:pending", part=part, attempt=attempt
    )
    result = recover_download_request(
        request.pk,
        actor_id=download_actor.pk,
        note="Retomar a conciliação",
        dispatch=False,
    )
    part.refresh_from_db()
    assert part.status == "waiting"
    assert RemoteSubmissionBarrier.objects.filter(part=part).exists()
    assert result.resumed_parts == (part.pk,)


def test_recovery_rejects_failed_request_when_repeat_is_active(
    download_company, download_actor
):
    from apps.fiscal.services.download_recovery import recover_download_request
    from apps.fiscal.services.downloads import request_download

    arguments = dict(
        company_id=download_company.pk,
        period=Period(date(2024, 1, 1), date(2024, 1, 2)),
        formats=("xml",),
        actor_id=download_actor.pk,
        trigger="manual",
        dispatch=False,
    )
    original = request_download(**arguments)
    original.parts.update(status="failed")
    original.status = "failed"
    original.save(update_fields=["status"])
    repeat = request_download(**arguments, repeat_of=original.pk)

    with pytest.raises(ValidationError, match="ativo"):
        recover_download_request(
            original.pk,
            actor_id=download_actor.pk,
            note="Retomar pedido anterior",
            dispatch=False,
        )

    original.refresh_from_db()
    repeat.refresh_from_db()
    assert original.status == "failed"
    assert original.parts.get().status == "failed"
    assert repeat.status == "queued"


@pytest.mark.django_db(transaction=True)
def test_postgres_recovery_does_not_deadlock_worker_finishing_a_part(
    download_company, download_actor
):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    from django.db import close_old_connections, connection, transaction

    from apps.fiscal.models import DownloadPart
    from apps.fiscal.services.download_recovery import recover_download_request
    from apps.fiscal.services.downloads import consolidate_request, request_download

    if connection.vendor != "postgresql":
        pytest.skip("Requires PostgreSQL row locks")
    request = request_download(
        company_id=download_company.pk,
        period=Period(date(2024, 1, 1), date(2024, 1, 2)),
        formats=("xml", "txt"),
        actor_id=download_actor.pk,
        trigger="manual",
        dispatch=False,
    )
    part = request.parts.first()
    worker_holds_part, recovery_wants_parts = Event(), Event()

    def configure_connection():
        close_old_connections()
        with connection.cursor() as cursor:
            cursor.execute("SET lock_timeout = '3s'")

    def worker():
        configure_connection()
        try:
            with transaction.atomic():
                current = DownloadPart.objects.select_for_update().get(pk=part.pk)
                worker_holds_part.set()
                assert recovery_wants_parts.wait(5)
                current.status = "empty"
                current.save(update_fields=["status"])
                consolidate_request(request.pk)
        finally:
            connection.close()

    def observe_part_lock(execute, sql, params, many, context):
        if "fiscal_downloadpart" in sql and "FOR UPDATE" in sql:
            recovery_wants_parts.set()
        return execute(sql, params, many, context)

    def recover():
        configure_connection()
        try:
            assert worker_holds_part.wait(5)
            with connection.execute_wrapper(observe_part_lock):
                return recover_download_request(
                    request.pk,
                    actor_id=download_actor.pk,
                    note="Retomar após execução concorrente",
                    dispatch=False,
                )
        finally:
            connection.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        worker_future = executor.submit(worker)
        recovery_future = executor.submit(recover)
        worker_future.result(timeout=12)
        result = recovery_future.result(timeout=12)
    part.refresh_from_db()
    assert part.status == "empty"
    assert part.pk not in result.resumed_parts
    assert len(result.resumed_parts) == 1
