from concurrent.futures import ThreadPoolExecutor
from datetime import date
from threading import Event

import pytest
from django.core.exceptions import PermissionDenied
from django.db import close_old_connections, connection, connections, transaction

from apps.fiscal.atf.types import Period
from apps.fiscal.models import DownloadPart, InvoiceDocument
from apps.fiscal.services.download_lifecycle import cancel_download_request
from apps.fiscal.services.downloads import advance_part
from apps.organizations.models import AccountingOffice, ClientCompany
from tests.test_download_execution import Portal


def require_postgres():
    if connection.vendor != "postgresql":
        pytest.skip("Requires PostgreSQL row locks")


@pytest.mark.django_db(transaction=True)
def test_cancel_during_inflight_submission_fences_worker(
    lifecycle_request, lifecycle_admin, tmp_path
):
    require_postgres()
    submitted, cancelled = Event(), Event()
    request = lifecycle_request
    part = request.parts.get(format="xml")

    class PausedPortal(Portal):
        def submit_query(self, *args, **kwargs):
            receipt = super().submit_query(*args, **kwargs)
            submitted.set()
            assert cancelled.wait(10)
            return receipt

    portal = PausedPortal(tmp_path, Period(part.start_date, part.end_date))

    def worker():
        close_old_connections()
        try:
            return advance_part(part.pk, client_factory=portal.open, dispatch=False)
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=1) as executor:
        pending = executor.submit(worker)
        try:
            assert submitted.wait(10)
            cancel_download_request(
                request.pk,
                actor_id=lifecycle_admin.pk,
                note="Cancelamento concorrente",
                acknowledge_remote_uncertainty=True,
            )
        finally:
            cancelled.set()
        assert pending.result(timeout=15).status == "cancelled"
    assert len(portal.submissions) == 1
    assert not request.parts.exclude(status="cancelled").exists()


@pytest.mark.django_db(transaction=True)
def test_indexing_foreign_key_does_not_deadlock_company_cancellation(
    lifecycle_request, lifecycle_admin
):
    require_postgres()
    part_locked, company_locked = Event(), Event()
    request = lifecycle_request
    part = request.parts.first()

    def indexer():
        close_old_connections()
        try:
            with transaction.atomic():
                DownloadPart.objects.select_for_update().get(pk=part.pk)
                part_locked.set()
                assert company_locked.wait(10)
                InvoiceDocument.objects.create(
                    company_id=request.company_id,
                    access_key="1" * 44,
                    issued_on=date(2024, 10, 10),
                    model="55",
                    number=1,
                )
        finally:
            connections.close_all()

    def cancel():
        close_old_connections()

        def observe_company_lock(execute, sql, params, many, context):
            result = execute(sql, params, many, context)
            if "organizations_clientcompany" in sql and "FOR" in sql:
                company_locked.set()
            return result

        try:
            with connection.cursor() as cursor:
                cursor.execute("SET lock_timeout = '5s'")
            with connection.execute_wrapper(observe_company_lock):
                return cancel_download_request(
                    request.pk,
                    actor_id=lifecycle_admin.pk,
                    note="Cancelar com indexador ativo",
                    acknowledge_remote_uncertainty=True,
                )
        finally:
            company_locked.set()
            connections.close_all()

    with ThreadPoolExecutor(max_workers=2) as executor:
        indexed = executor.submit(indexer)
        assert part_locked.wait(10)
        canceled = executor.submit(cancel)
        indexed.result(timeout=15)
        assert canceled.result(timeout=15).status == "cancelled"
    assert InvoiceDocument.objects.filter(company_id=request.company_id).exists()


@pytest.mark.django_db(transaction=True)
def test_cancel_rechecks_office_after_waiting_for_company_transfer(
    lifecycle_request, lifecycle_admin
):
    require_postgres()
    waiting = Event()
    request = lifecycle_request
    other = AccountingOffice.objects.create(
        legal_name="Outro escritório fictício", tax_identifier="11444777000161"
    )

    def cancel():
        close_old_connections()

        def before_company_lock(execute, sql, params, many, context):
            if "organizations_clientcompany" in sql and "FOR" in sql:
                waiting.set()
            return execute(sql, params, many, context)

        try:
            with connection.execute_wrapper(before_company_lock):
                return cancel_download_request(
                    request.pk,
                    actor_id=lifecycle_admin.pk,
                    note="Escritório anterior",
                    acknowledge_remote_uncertainty=True,
                )
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=1) as executor:
        with transaction.atomic():
            company = ClientCompany.objects.select_for_update().get(
                pk=request.company_id
            )
            company.office = other
            company.save(update_fields=["office"])
            canceled = executor.submit(cancel)
            assert waiting.wait(10)
        with pytest.raises(PermissionDenied):
            canceled.result(timeout=15)
    request.refresh_from_db()
    assert request.status == "queued"


@pytest.mark.django_db(transaction=True)
def test_cleanup_part_locks_do_not_lock_joined_request(lifecycle_request):
    from apps.fiscal.models import DownloadRequest
    from apps.fiscal.services.download_deletion import lock_company_parts

    require_postgres()
    request = lifecycle_request

    def cleanup_locks():
        close_old_connections()
        try:
            with transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute("SET LOCAL lock_timeout = '3s'")
                lock_company_parts(request.company_id)
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=1) as executor:
        with transaction.atomic():
            DownloadRequest.objects.select_for_update().get(pk=request.pk)
            executor.submit(cleanup_locks).result(timeout=8)


@pytest.mark.django_db(transaction=True)
def test_physical_cleanup_waits_for_publishers_in_other_companies(
    lifecycle_request, lifecycle_admin, tmp_path, settings
):
    from apps.fiscal.models import DownloadArchive, DownloadFileDeletion
    from apps.fiscal.services.download_deletion import purge_request_files
    from apps.fiscal.services.download_lifecycle import (
        delete_cancelled_download_request,
    )
    from apps.fiscal.services.storage_coordination import lock_fiscal_storage

    require_postgres()
    settings.FISCAL_NOTES_ROOT = tmp_path
    target = tmp_path / "reused.zip"
    target.write_bytes(b"shared physical data")
    request = lifecycle_request
    cancel_download_request(
        request.pk,
        actor_id=lifecycle_admin.pk,
        note="Cancelar",
        acknowledge_remote_uncertainty=True,
    )
    delete_cancelled_download_request(
        request.pk, actor_id=lifecycle_admin.pk, note="Excluir", dispatch=False
    )
    DownloadFileDeletion.objects.create(request=request, path="reused.zip")
    other_company = ClientCompany.objects.create(
        office=request.company.office,
        legal_name="Outra empresa fictícia",
        tax_identifier="11444777000161",
    )
    from apps.fiscal.models import DownloadRequest

    other = DownloadRequest.objects.create(
        company=other_company,
        start_date=request.start_date,
        end_date=request.end_date,
        active_key="namespace-reuse",
        formats=["xml"],
    )
    other_part = DownloadPart.objects.create(
        request=other,
        start_date=request.start_date,
        end_date=request.end_date,
        format="xml",
    )
    cleanup_started, cleanup_finished = Event(), Event()

    def cleanup():
        close_old_connections()

        def observe_cleanup(execute, sql, params, many, context):
            if "pg_advisory_xact_lock(" in sql:
                cleanup_started.set()
            return execute(sql, params, many, context)

        try:
            with connection.execute_wrapper(observe_cleanup):
                return purge_request_files(request.pk)
        finally:
            cleanup_finished.set()
            connections.close_all()

    with ThreadPoolExecutor(max_workers=1) as executor:
        with transaction.atomic():
            lock_fiscal_storage()
            pending = executor.submit(cleanup)
            assert cleanup_started.wait(10)
            assert not cleanup_finished.is_set()
            # This reference is invisible to cleanup until the publisher commits.
            DownloadArchive.objects.create(
                part=other_part,
                remote_account_key="a" * 64,
                message_id="shared-path",
                attachment_index=0,
                filename="reused.zip",
                path="reused.zip",
                sha256="b" * 64,
                byte_count=20,
            )
        pending.result(timeout=15)
    assert target.read_bytes() == b"shared physical data"
    assert DownloadFileDeletion.objects.get(request=request).outcome == "shared"
