from datetime import date

import pytest


@pytest.mark.parametrize("model", ["55", "65"])
@pytest.mark.parametrize(
    ("start", "end"),
    [
        (date(2024, 1, 31), date(2024, 3, 2)),
        (date(2024, 10, 1), date(2024, 10, 20)),
        (date(2024, 12, 31), date(2025, 1, 2)),
    ],
)
@pytest.mark.parametrize("formats", [("xml",), ("txt",), ("xml", "txt")])
def test_requests_preserve_full_period_once_per_format(
    download_company, download_actor, model, start, end, formats
):
    from apps.fiscal.atf.types import Period
    from apps.fiscal.services.downloads import request_download

    request = request_download(
        company_id=download_company.pk,
        actor_id=download_actor.pk,
        period=Period(start, end),
        document_model=model,
        formats=formats,
        trigger="manual",
        dispatch=False,
    )
    assert set(request.parts.values_list("start_date", "end_date", "format")) == {
        (start, end, format) for format in formats
    }


@pytest.mark.parametrize("model", ["55", "65"])
def test_full_period_is_submitted_only_once_per_format(
    tmp_path, download_company, download_actor, settings, model
):
    from datetime import timedelta

    from django.utils import timezone

    from apps.fiscal.atf.types import Period
    from apps.fiscal.services.downloads import advance_part, request_download
    from tests.test_download_execution import Portal
    from tests.test_nfce_downloads import NfcePortal

    settings.FISCAL_NOTES_ROOT = tmp_path / "notes"
    period = Period(date(2024, 9, 25), date(2024, 11, 2))
    portal = (NfcePortal if model == "65" else Portal)(tmp_path, period)
    if model == "65":
        portal.ready = True
    request = request_download(
        company_id=download_company.pk,
        actor_id=download_actor.pk,
        period=period,
        document_model=model,
        formats=("xml", "txt"),
        trigger="manual",
        dispatch=False,
    )
    now = timezone.now()
    assert request.parts.count() == 2
    for part in request.parts.all():
        assert (
            advance_part(
                part.pk, client_factory=portal.open, now=now, dispatch=False
            ).status
            == "waiting"
        )
        now += timedelta(seconds=61)
        assert (
            advance_part(
                part.pk, client_factory=portal.open, now=now, dispatch=False
            ).status
            == "succeeded"
        )
        now += timedelta(seconds=61)
    assert sorted(portal.submissions, key=lambda item: item[1]) == [
        (period, "txt"),
        (period, "xml"),
    ]


def test_scheduled_requests_use_one_full_period_per_model(download_company, settings):
    from datetime import UTC, datetime, time

    from apps.fiscal.models import DownloadPolicy
    from apps.fiscal.services.scheduling import enqueue_due_downloads

    settings.ATF_PB_ENABLED = True
    DownloadPolicy.objects.create(
        company=download_company,
        mode="automatic",
        is_active=True,
        scheduled_time=time(2),
        period_strategy="rolling_days",
        rolling_days=45,
        document_models=["55", "65"],
        formats=["xml", "txt"],
    )
    assert (
        enqueue_due_downloads(now=datetime(2024, 11, 2, 6, tzinfo=UTC), dispatch=False)
        == 2
    )
    for request in download_company.download_requests.all():
        assert request.parts.count() == 2
        assert set(request.parts.values_list("start_date", "end_date")) == {
            (date(2024, 9, 18), date(2024, 11, 1))
        }


def test_period_rejects_inverted_dates():
    from apps.fiscal.atf.types import Period

    with pytest.raises(ValueError):
        Period(date(2024, 2, 2), date(2024, 2, 1))


def test_active_key_normalizes_format_order():
    from apps.fiscal.atf.types import Period
    from apps.fiscal.services.periods import active_request_key

    period = Period(date(2024, 1, 1), date(2024, 1, 31))
    assert active_request_key(1, period, ("xml", "txt")) == active_request_key(
        1, period, ("txt", "xml")
    )
    assert active_request_key(1, period, ("xml",)) != active_request_key(
        2, period, ("xml",)
    )
