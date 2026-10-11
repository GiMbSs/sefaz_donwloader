from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier

import pytest
from django.db import close_old_connections, connection
from django.utils import timezone

from apps.fiscal.models import NsuControl, SyncPolicy, SyncRequest
from apps.fiscal.services.execution import _claim_sync_request
from apps.fiscal.services.sync import _release_waiting_synchronizations
from tests.test_distribution_reprocessing import _company
from tests.test_sync_execution import _certificate


@pytest.mark.django_db(transaction=True)
def test_postgres_wait_release_and_worker_claim_do_not_deadlock(monkeypatch):
    if connection.vendor != "postgresql":
        pytest.skip("Requires PostgreSQL row locks")
    now = timezone.now()
    company = _company()
    company.fiscal_environment = "production"
    company.save()
    _certificate(company, now=now)
    SyncPolicy.objects.create(company=company, mode="manual")
    NsuControl.objects.create(
        company=company,
        environment="production",
        next_allowed_at=now - timedelta(hours=1),
    )
    request = SyncRequest.objects.create(
        company=company, environment="production", trigger="manual", status="waiting"
    )
    monkeypatch.setattr(
        "apps.fiscal.services.sync._dispatch_sync_request", lambda pk: lambda: None
    )
    barrier = Barrier(2)

    def run(operation):
        close_old_connections()
        try:
            with connection.cursor() as cursor:
                cursor.execute("SET lock_timeout TO '3s'")
                cursor.execute("SET statement_timeout TO '8s'")
            barrier.wait(timeout=5)
            return operation()
        finally:
            connection.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        release = pool.submit(run, lambda: _release_waiting_synchronizations(now=now))
        claim = pool.submit(
            run, lambda: _claim_sync_request(sync_request_id=request.pk, now=now)
        )
        assert release.result(timeout=12) == 1
        claim.result(timeout=12)
    request.refresh_from_db()
    assert request.status in {"queued", "running"}
