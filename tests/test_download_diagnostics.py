import logging
from contextlib import contextmanager
from datetime import date

import pytest
import requests

from apps.fiscal.atf.errors import AtfTransientError
from apps.fiscal.atf.types import Period
from apps.fiscal.services.downloads import advance_part, request_download
from apps.operations.models import OperationAlert
from tests.test_atf_authentication import Response, Session


def make_request(company, actor):
    return request_download(
        company_id=company.pk,
        actor_id=actor.pk,
        period=Period(date(2024, 10, 1), date(2024, 10, 18)),
        formats=("xml",),
        trigger="manual",
        dispatch=False,
    )


def test_disabled_integration_records_actionable_reason_and_safe_worker_log(
    download_company, download_actor, settings, caplog
):
    settings.ATF_PB_ENABLED = False
    request = make_request(download_company, download_actor)
    part = request.parts.get()
    with caplog.at_level(logging.WARNING):
        result = advance_part(part.pk, dispatch=False)
    part.refresh_from_db()
    assert result.status == "failed"
    assert part.error_code == "atf_not_enabled"
    assert part.attempts.get().error_code == "atf_not_enabled"
    assert str(request.pk) in caplog.text
    assert str(part.pk) in caplog.text
    assert "operation=connect" in caplog.text
    assert "code=atf_not_enabled" in caplog.text
    alert = OperationAlert.objects.get(company=download_company)
    assert "desativada" in (alert.title + alert.message).lower()
    assert "ATF_PB_ENABLED=True" in alert.message


def test_failed_request_explains_recovery_without_promising_pending_files(
    client, download_company, download_actor, settings
):
    settings.ATF_PB_ENABLED = False
    request = make_request(download_company, download_actor)
    advance_part(request.parts.get().pk, dispatch=False)
    client.force_login(download_actor)
    page = client.get(f"/downloads/{request.pk}/").content.decode()
    assert "ATF_PB_ENABLED=True" in page
    assert "atf_not_enabled" in page
    assert "Os arquivos aparecerão aqui após" not in page
    assert "Retomar pedido" in page
    alerts = client.get("/alertas/").content.decode()
    assert f"/downloads/{request.pk}/" in alerts


def test_unexpected_local_failure_is_recorded_without_exposing_exception_payload(
    download_company, download_actor, caplog
):
    @contextmanager
    def broken_client(company_id):
        raise RuntimeError("password=secret-value cookie=private-session")
        yield  # pragma: no cover

    request = make_request(download_company, download_actor)
    with caplog.at_level(logging.WARNING):
        result = advance_part(
            request.parts.get().pk, client_factory=broken_client, dispatch=False
        )
    assert result.status == "failed"
    part = request.parts.get()
    assert part.error_code == "atf_unexpected_error"
    assert part.attempts.get().finished_at is not None
    assert "RuntimeError" in caplog.text
    assert "broken_client" in caplog.text
    assert "secret-value" not in caplog.text
    assert "private-session" not in caplog.text
    assert "secret-value" not in OperationAlert.objects.get().message


def test_transient_failures_keep_retry_and_do_not_log_raw_exception_text(
    download_company, download_actor, caplog
):
    @contextmanager
    def unavailable(company_id):
        raise AtfTransientError("private-url?password=secret-value")
        yield  # pragma: no cover

    request = make_request(download_company, download_actor)
    with caplog.at_level(logging.WARNING):
        result = advance_part(
            request.parts.get().pk, client_factory=unavailable, dispatch=False
        )
    assert result.next_eta is not None
    part = request.parts.get()
    assert part.retry_count == 1
    assert part.error_code == "atf_transient_error"
    assert "code=atf_transient_error" in caplog.text
    assert "secret-value" not in caplog.text


@pytest.mark.parametrize(
    ("failure", "expected"),
    [
        (requests.Timeout("secret-url"), "atf_connection_timeout"),
        (requests.ConnectionError("secret-url"), "atf_connection_failed"),
        (Response(status=503), "atf_remote_unavailable"),
        (Response(status=429), "atf_rate_limited"),
    ],
)
def test_client_distinguishes_network_failure_reasons(tmp_path, failure, expected):
    from apps.fiscal.atf.client import AtfPbClient

    client = AtfPbClient(Session([failure]), "00000000000191", tmp_path)
    with pytest.raises(AtfTransientError) as caught:
        client.authenticate()
    assert str(caught.value) == expected
    assert "secret-url" not in str(caught.value)
    if isinstance(failure, Response):
        assert caught.value.http_status == failure.status_code


def test_unexpected_failure_after_submission_does_not_resend_on_recovery(
    download_company, download_actor, tmp_path, settings
):
    from datetime import timedelta

    from django.utils import timezone

    from apps.fiscal.models import RemoteSubmissionBarrier
    from apps.fiscal.services.download_recovery import recover_download_request
    from tests.test_download_execution import Portal

    class BrokenAfterSending(Portal):
        def submit_query(self, identity, period, format, *, document_model="55"):
            super().submit_query(
                identity, period, format, document_model=document_model
            )
            raise RuntimeError("sensitive payload that must stay private")

    portal = BrokenAfterSending(tmp_path, Period(date(2024, 10, 1), date(2024, 10, 18)))

    @contextmanager
    def factory(company_id):
        yield portal

    settings.FISCAL_NOTES_ROOT = tmp_path / "notes"
    request = make_request(download_company, download_actor)
    part = request.parts.get()
    assert (
        advance_part(part.pk, client_factory=factory, dispatch=False).status == "failed"
    )
    part.refresh_from_db()
    assert part.attempts.get().submission_certainty == "uncertain"
    assert RemoteSubmissionBarrier.objects.filter(part=part).exists()
    recover_download_request(
        request.pk, actor_id=download_actor.pk, note="Test recovery", dispatch=False
    )
    result = advance_part(
        part.pk,
        client_factory=factory,
        now=timezone.now() + timedelta(minutes=2),
        dispatch=False,
    )
    assert result.status == "succeeded"
    assert len(portal.submissions) == 1
