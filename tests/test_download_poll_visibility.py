import logging
from datetime import date, timedelta

from django.utils import timezone

from apps.fiscal.atf.types import Period
from apps.fiscal.services.downloads import advance_part, request_download
from tests.test_download_execution import Portal


def test_uncertain_post_shows_automatic_wait_without_empty_manual_review(
    client, download_company, download_actor, tmp_path
):
    period = Period(date(2024, 10, 1), date(2024, 10, 18))
    request = request_download(
        company_id=download_company.pk,
        actor_id=download_actor.pk,
        trigger="manual",
        period=period,
        formats=("txt",),
        dispatch=False,
    )
    portal = Portal(tmp_path, period, uncertain=True)
    advance_part(request.parts.get().pk, client_factory=portal.open, dispatch=False)
    client.force_login(download_actor)
    response = client.get(f"/downloads/{request.pk}/")
    content = response.content.decode()
    assert "Aguardando confirmação do envio" in content
    assert "Próxima verificação prevista" in content
    assert "Conferir resultado" not in content


def test_beat_recovery_logs_manual_parts_even_without_new_scheduled_requests(
    download_company, download_actor, monkeypatch, caplog, settings
):
    from types import SimpleNamespace

    from apps.fiscal.services.scheduling import enqueue_due_downloads

    settings.ATF_PB_ENABLED = True
    request = request_download(
        company_id=download_company.pk,
        actor_id=download_actor.pk,
        trigger="manual",
        period=Period(date(2024, 10, 1), date(2024, 10, 18)),
        formats=("xml", "txt"),
        dispatch=False,
    )
    request.status = "waiting"
    request.save()
    request.parts.update(next_poll_at=timezone.now() - timedelta(minutes=1))
    sent = []

    def publish(*, args, eta):
        sent.extend(args)
        return SimpleNamespace(id="synthetic-celery-task")

    monkeypatch.setattr("apps.fiscal.tasks.process_download_part.apply_async", publish)
    with caplog.at_level(logging.INFO):
        created = enqueue_due_downloads(now=timezone.now())
    assert created == 0
    assert set(sent) == {str(part.pk) for part in request.parts.all()}
    assert "created_requests=0" in caplog.text
    assert "recovered_parts=2" in caplog.text
    assert "event=atf_part_dispatched" in caplog.text


def test_failed_broker_publish_is_not_reported_as_recovered_part(
    download_company, download_actor, monkeypatch, caplog, settings
):
    from apps.fiscal.services.scheduling import enqueue_due_downloads
    from apps.operations.models import OperationAlert

    settings.ATF_PB_ENABLED = True
    request = request_download(
        company_id=download_company.pk,
        actor_id=download_actor.pk,
        trigger="manual",
        period=Period(date(2024, 10, 1), date(2024, 10, 18)),
        formats=("xml",),
        dispatch=False,
    )
    request.parts.update(next_poll_at=timezone.now() - timedelta(minutes=1))

    def offline(*, args, eta):
        raise ConnectionError("redis://private-password@private-host")

    monkeypatch.setattr("apps.fiscal.tasks.process_download_part.apply_async", offline)
    with caplog.at_level(logging.INFO):
        enqueue_due_downloads(now=timezone.now())
    assert "recovered_parts=0" in caplog.text
    assert "event=atf_dispatch_failed" in caplog.text
    assert "private-password" not in caplog.text
    assert OperationAlert.objects.filter(code="atf_queue_unavailable").exists()
