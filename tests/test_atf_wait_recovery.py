from dataclasses import replace
from datetime import date, timedelta
from types import SimpleNamespace

import pytest
from django.utils import timezone

from apps.fiscal.atf.types import Period
from apps.fiscal.services.downloads import advance_part, request_download
from tests.test_download_execution import Portal
from tests.test_nfce_downloads import NfcePortal


class PendingPortal(Portal):
    ready = False

    def read_message(self, *args):
        message = super().read_message(*args)
        return (
            message
            if self.ready
            else replace(message, attachments=(), outcome="pending")
        )


def test_submission_timestamp_excludes_slow_preparation(
    make_part, tmp_path, monkeypatch
):
    clock = [1000.0]
    monkeypatch.setattr(
        "apps.fiscal.services.downloads.time.monotonic", lambda: clock[0]
    )

    class SlowPreparation(Portal):
        def lookup_issuer(self, *args, **kwargs):
            clock[0] += 75
            return super().lookup_issuer(*args, **kwargs)

    part = make_part()
    portal = SlowPreparation(
        tmp_path, Period(part.start_date, part.end_date), uncertain=True
    )
    now = timezone.now()
    advance_part(part.pk, client_factory=portal.open, now=now, dispatch=False)
    part.refresh_from_db()
    assert part.submitted_at >= now + timedelta(seconds=75)
    assert part.next_poll_at >= now + timedelta(seconds=135)


@pytest.fixture
def make_part(download_company, download_actor, settings, tmp_path):
    settings.FISCAL_NOTES_ROOT = tmp_path / "notes"

    def make(model="55"):
        request = request_download(
            company_id=download_company.pk,
            period=Period(date(2024, 10, 1), date(2024, 10, 18)),
            formats=("txt",),
            actor_id=download_actor.pk,
            trigger="manual",
            document_model=model,
            dispatch=False,
        )
        return request.parts.get()

    return make


@pytest.mark.parametrize("model", ["55", "65"])
@pytest.mark.parametrize("uncertain", [False, True])
def test_first_poll_waits_a_full_minute_after_slow_submission_finishes(
    make_part, tmp_path, monkeypatch, model, uncertain
):
    clock = [1000.0]
    monkeypatch.setattr(
        "apps.fiscal.services.downloads.time.monotonic", lambda: clock[0]
    )
    base = NfcePortal if model == "65" else Portal

    class SlowPortal(base):
        ready = True

        def submit_query(self, *args, **kwargs):
            try:
                return super().submit_query(*args, **kwargs)
            finally:
                clock[0] += 75

    part = make_part(model)
    portal = SlowPortal(
        tmp_path, Period(part.start_date, part.end_date), uncertain=uncertain
    )
    now = timezone.now()
    result = advance_part(part.pk, client_factory=portal.open, now=now, dispatch=False)
    assert result.next_eta >= now + timedelta(seconds=135)
    part.refresh_from_db()
    assert part.status == "waiting"
    assert len(portal.submissions) == 1
    advance_part(
        part.pk,
        client_factory=portal.open,
        now=now + timedelta(seconds=134),
        dispatch=False,
    )
    assert part.attempts.count() == 1
    assert (
        advance_part(
            part.pk,
            client_factory=portal.open,
            now=now + timedelta(seconds=136),
            dispatch=False,
        ).status
        == "succeeded"
    )
    assert len(portal.submissions) == 1


def test_early_delivery_is_republished_without_opening_a_sefaz_session(
    make_part, monkeypatch
):
    part = make_part()
    now = timezone.now()
    part.next_poll_at = now + timedelta(seconds=30)
    part.save(update_fields=["next_poll_at"])
    published = []

    def publish(*, args, eta):
        published.append((args, eta))
        return SimpleNamespace(id="deferred")

    def forbidden_session(company_id):
        raise AssertionError("Early task must not access SEFAZ")

    monkeypatch.setattr("apps.fiscal.tasks.process_download_part.apply_async", publish)
    advance_part(part.pk, client_factory=forbidden_session, now=now)
    assert published == [([str(part.pk)], part.next_poll_at)]
    assert part.attempts.count() == 0


def test_busy_company_lease_gets_a_new_attempt_without_network(make_part, monkeypatch):
    from apps.fiscal.services.leases import claim_access, company_scope

    part = make_part()
    now = timezone.now()
    claim_access(company_scope(part.request.company.tax_identifier), part.pk, now=now)
    published = []

    def publish(*, args, eta):
        published.append((args, eta))
        return SimpleNamespace(id="busy")

    monkeypatch.setattr("apps.fiscal.tasks.process_download_part.apply_async", publish)
    advance_part(part.pk, now=now)
    assert len(published) == 1
    assert published[0][1] >= now + timedelta(seconds=60)
    assert part.attempts.count() == 0


def test_uncertain_submission_and_healthy_wait_are_not_failure_alerts(
    make_part, tmp_path
):
    from apps.operations.models import OperationAlert

    part = make_part()
    portal = PendingPortal(
        tmp_path, Period(part.start_date, part.end_date), uncertain=True
    )
    now = timezone.now()
    advance_part(part.pk, client_factory=portal.open, now=now, dispatch=False)
    part.refresh_from_db()
    assert part.status == "waiting"
    assert not OperationAlert.objects.filter(company=part.request.company).exists()
    submission = part.attempts.get(operation="submit")
    assert submission.error_code == "atf_submission_uncertain"
    assert submission.submission_certainty == "uncertain"
    advance_part(
        part.pk,
        client_factory=portal.open,
        now=now + timedelta(seconds=61),
        dispatch=False,
    )
    part.refresh_from_db()
    assert part.status == "waiting"
    assert part.error_code == ""
    assert part.retry_count == 0
    assert not OperationAlert.objects.filter(company=part.request.company).exists()
    portal.ready = True
    assert (
        advance_part(
            part.pk,
            client_factory=portal.open,
            now=now + timedelta(seconds=122),
            dispatch=False,
        ).status
        == "succeeded"
    )
    assert len(portal.submissions) == 1


def test_scheduled_uncertain_query_automatically_polls_then_downloads_same_request(
    download_company,
    tmp_path,
    settings,
    monkeypatch,
    django_capture_on_commit_callbacks,
):
    from datetime import time

    from apps.fiscal.models import DownloadPolicy, RemoteSubmissionBarrier

    settings.FISCAL_NOTES_ROOT = tmp_path / "notes"
    DownloadPolicy.objects.create(
        company=download_company,
        mode="automatic",
        is_active=True,
        scheduled_time=time(2),
        formats=["txt"],
    )
    period = Period(date(2024, 10, 1), date(2024, 10, 18))
    request = request_download(
        company_id=download_company.pk,
        period=period,
        formats=("txt",),
        actor_id=None,
        trigger="scheduled",
        dispatch=False,
    )
    portal = PendingPortal(tmp_path, period, uncertain=True)
    now = timezone.now() + timedelta(days=1)
    deliveries = []

    def publish(*, args, eta):
        deliveries.append((args, eta))
        return SimpleNamespace(id="scheduled-poll")

    monkeypatch.setattr("apps.fiscal.tasks.process_download_part.apply_async", publish)
    part = request.parts.get()
    with django_capture_on_commit_callbacks(execute=True):
        result = advance_part(part.pk, client_factory=portal.open, now=now)
    assert result.status == "waiting"
    assert len(deliveries) == 1
    args, eta = deliveries.pop()
    assert args == [str(part.pk)]
    assert eta >= now + timedelta(minutes=1)
    with django_capture_on_commit_callbacks(execute=True):
        result = advance_part(args[0], client_factory=portal.open, now=eta)
    assert result.status == "waiting"
    assert len(deliveries) == 1
    args, eta = deliveries.pop()
    portal.ready = True
    with django_capture_on_commit_callbacks(execute=True):
        result = advance_part(args[0], client_factory=portal.open, now=eta)
    request.refresh_from_db()
    assert result.status == request.status == "succeeded"
    assert part.archives.count() == 1
    assert len(portal.submissions) == 1
    assert not RemoteSubmissionBarrier.objects.filter(part=part).exists()


def test_manual_recovery_preserves_initial_wait_and_never_reposts(
    make_part, tmp_path, download_actor, monkeypatch, django_capture_on_commit_callbacks
):
    from apps.fiscal.services.download_recovery import recover_download_request

    part = make_part()
    portal = Portal(tmp_path, Period(part.start_date, part.end_date), uncertain=True)
    now = timezone.now()
    advance_part(part.pk, client_factory=portal.open, now=now, dispatch=False)
    part.refresh_from_db()
    earliest = part.next_poll_at
    published = []

    def publish(*, args, eta):
        published.append((args, eta))
        return SimpleNamespace(id="recover")

    monkeypatch.setattr("apps.fiscal.tasks.process_download_part.apply_async", publish)
    with django_capture_on_commit_callbacks(execute=True):
        recover_download_request(
            part.request_id, actor_id=download_actor.pk, note="Retomar acompanhamento"
        )
    part.refresh_from_db()
    assert part.next_poll_at >= earliest
    assert published == [([str(part.pk)], part.next_poll_at)]
    assert (
        advance_part(
            part.pk,
            client_factory=portal.open,
            now=part.next_poll_at + timedelta(seconds=1),
            dispatch=False,
        ).status
        == "succeeded"
    )
    assert len(portal.submissions) == 1
