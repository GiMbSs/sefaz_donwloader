from datetime import date, timedelta

import pytest
from django.utils import timezone


@pytest.fixture
def part(download_company):
    from apps.fiscal.models import DownloadPart, DownloadRequest

    request = DownloadRequest.objects.create(
        company=download_company,
        start_date=date(2024, 1, 1),
        end_date=date(2024, 1, 31),
        active_key="one",
        formats=["xml"],
    )
    return DownloadPart.objects.create(
        request=request,
        start_date=request.start_date,
        end_date=request.end_date,
        format="xml",
        remote_account_key="a" * 64,
    )


def test_expired_lease_does_not_clear_uncertain_submission(part):
    from apps.fiscal.atf.errors import AtfSubmissionUncertain
    from apps.fiscal.atf.types import SubmissionEvidence
    from apps.fiscal.models import DownloadAttempt, RemoteSubmissionBarrier
    from apps.fiscal.services.leases import (
        begin_submission,
        claim_access,
        company_scope,
    )

    now = timezone.now()
    scope = company_scope(part.request.company.tax_identifier)
    claim_access(scope, part.pk, now=now)
    token = claim_access("account:" + part.remote_account_key, part.pk, now=now)
    attempt = DownloadAttempt.objects.create(part=part, operation="submit")
    evidence = SubmissionEvidence(part.pk, attempt.pk, (), now)
    begin_submission(part.pk, token, evidence, now=now)
    later = now + timedelta(minutes=10)
    claim_access(scope, part.pk, now=later)
    replacement = claim_access("account:" + part.remote_account_key, part.pk, now=later)
    with pytest.raises(AtfSubmissionUncertain):
        begin_submission(part.pk, replacement, evidence, now=later)
    assert RemoteSubmissionBarrier.objects.filter(part=part).count() == 2


def test_stale_owner_cannot_renew_or_release_new_lease(part):
    from apps.fiscal.atf.errors import AtfPermissionError
    from apps.fiscal.services.leases import claim_access, release_access, renew_access

    now = timezone.now()
    token = claim_access("account:test", part.pk, now=now)
    later = now + timedelta(minutes=10)
    newer = claim_access("account:test", part.pk, now=later)
    with pytest.raises(AtfPermissionError):
        renew_access(token, now=later)
    release_access(token)
    assert claim_access("account:test", part.pk, now=later) is None
    release_access(newer)


def test_binding_does_not_release_barrier_before_archive_validation(part):
    from apps.fiscal.models import DownloadAttempt, RemoteSubmissionBarrier
    from apps.fiscal.services.leases import bind_remote_result

    attempt = DownloadAttempt.objects.create(part=part, operation="submit")
    RemoteSubmissionBarrier.objects.create(
        scope="account:pending", part=part, attempt=attempt
    )
    part.candidates = ["20"]
    part.save()
    bind_remote_result(part.pk, part.remote_account_key, "20", actor_id=None)
    assert RemoteSubmissionBarrier.objects.filter(part=part).exists()


def test_remote_group_cannot_be_bound_to_two_parts(part):
    from apps.fiscal.atf.errors import AtfAmbiguousResult
    from apps.fiscal.models import DownloadPart
    from apps.fiscal.services.leases import bind_remote_result

    part.candidates = ["20"]
    part.save()
    bind_remote_result(part.pk, part.remote_account_key, "20", actor_id=None)
    second = DownloadPart.objects.create(
        request=part.request,
        start_date=part.start_date,
        end_date=part.end_date,
        format="txt",
        remote_account_key=part.remote_account_key,
        candidates=["20"],
    )
    with pytest.raises(AtfAmbiguousResult):
        bind_remote_result(second.pk, second.remote_account_key, "20", actor_id=None)


@pytest.mark.django_db(transaction=True)
def test_postgres_claim_grants_only_one_concurrent_owner(part):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from django.db import close_old_connections, connection, connections

    from apps.fiscal.services.leases import claim_access

    if connection.vendor != "postgresql":
        pytest.skip("Requires PostgreSQL row locks")
    gate = Barrier(2)
    now = timezone.now()

    def claim():
        close_old_connections()
        try:
            gate.wait(timeout=10)
            return claim_access("account:concurrent", part.pk, now=now)
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(claim) for _ in range(2)]
        tokens = [future.result(timeout=15) for future in futures]
    assert sum(token is not None for token in tokens) == 1


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("operation", ["submit", "bind", "persist", "abandon"])
def test_postgres_part_operations_do_not_lock_joined_company_or_request(
    part, operation
):
    from concurrent.futures import ThreadPoolExecutor

    from django.db import close_old_connections, connection, transaction

    from apps.fiscal.atf.types import SubmissionEvidence
    from apps.fiscal.models import DownloadRequest
    from apps.fiscal.services.artifacts import persist_archive
    from apps.fiscal.services.download_recovery import abandon_uncertain_submission
    from apps.fiscal.services.leases import (
        begin_submission,
        bind_remote_result,
        claim_access,
    )
    from apps.organizations.models import ClientCompany

    if connection.vendor != "postgresql":
        pytest.skip("Requires PostgreSQL row locks")

    class PartLockChecked(Exception):
        pass

    def lock_related_rows():
        close_old_connections()
        try:
            with transaction.atomic():
                ClientCompany.objects.select_for_update(nowait=True).get(
                    pk=part.request.company_id
                )
                DownloadRequest.objects.select_for_update(nowait=True).get(
                    pk=part.request_id
                )
        finally:
            connection.close()

    def check_after_part_lock(execute, sql, params, many, context):
        result = execute(sql, params, many, context)
        if "fiscal_downloadpart" in sql and "FOR UPDATE" in sql:
            with ThreadPoolExecutor(max_workers=1) as executor:
                executor.submit(lock_related_rows).result(timeout=5)
            # Stop at the lock boundary; no network, files, or further writes.
            raise PartLockChecked()
        return result

    now = timezone.now()
    token = claim_access("account:" + part.remote_account_key, part.pk, now=now)
    evidence = SubmissionEvidence(part.pk, part.pk, (), now)
    with (
        pytest.raises(PartLockChecked),
        connection.execute_wrapper(check_after_part_lock),
    ):
        if operation == "submit":
            begin_submission(part.pk, token, evidence, now=now)
        elif operation == "bind":
            bind_remote_result(part.pk, part.remote_account_key, "20", actor_id=None)
        elif operation == "persist":
            persist_archive(part.pk, None, None, None)
        else:
            abandon_uncertain_submission(
                part.pk,
                actor_id=None,
                note="Lock regression",
                acknowledge_remote_uncertainty=True,
            )
