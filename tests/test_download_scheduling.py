from datetime import UTC, date, datetime, time
from importlib import import_module

import pytest

from apps.fiscal.models import DownloadPolicy


def _legacy_company(registry):
    office = registry.get_model("organizations", "AccountingOffice").objects.create(
        legal_name="Historical office", tax_identifier="00000000000191"
    )
    return registry.get_model("organizations", "ClientCompany").objects.create(
        office_id=office.pk,
        legal_name="Historical company",
        tax_identifier="00000000000191",
    )


@pytest.mark.parametrize(
    ("strategy", "now", "expected"),
    [
        (
            "previous_day",
            datetime(2024, 3, 1, 5, tzinfo=UTC),
            (date(2024, 2, 29), date(2024, 2, 29)),
        ),
        (
            "previous_month",
            datetime(2024, 3, 15, 5, tzinfo=UTC),
            (date(2024, 2, 1), date(2024, 2, 29)),
        ),
        (
            "rolling_days",
            datetime(2024, 3, 1, 5, tzinfo=UTC),
            (date(2024, 2, 23), date(2024, 2, 29)),
        ),
    ],
)
def test_policy_period_respects_local_complete_days(
    download_company, strategy, now, expected
):
    from apps.fiscal.services.scheduling import period_for_policy

    policy = DownloadPolicy(
        company=download_company, period_strategy=strategy, rolling_days=7
    )
    period = period_for_policy(policy, now)
    assert (period.start, period.end) == expected


@pytest.mark.parametrize("mode", ["automatic", "hybrid"])
@pytest.mark.django_db(transaction=True)
def test_migration_preserves_active_automatic_and_hybrid_schedules(legacy_schema, mode):
    migration = import_module(
        "apps.fiscal.migrations.0010_adapt_programmable_schedules"
    )
    company = _legacy_company(legacy_schema)
    original = legacy_schema.get_model("fiscal", "SyncPolicy").objects.create(
        company_id=company.pk,
        mode=mode,
        frequency="weekly",
        scheduled_time=time(4, 15),
        timezone="America/Sao_Paulo",
        weekdays=[1, 4],
        monthday=20,
        is_active=True,
    )
    migration.forwards(legacy_schema, None)
    migration.forwards(legacy_schema, None)
    adapted = legacy_schema.get_model("fiscal", "DownloadPolicy").objects.get(
        company_id=company.pk
    )
    assert adapted.mode == mode
    assert adapted.is_active
    assert adapted.scheduled_time == time(4, 15)
    assert adapted.timezone == "America/Sao_Paulo"
    assert adapted.weekdays == [1, 4]
    assert adapted.period_strategy == "rolling_days"
    assert adapted.formats == ["xml", "txt"]
    assert adapted.legacy_policy_id == original.pk


def test_cutover_resumes_active_schedule_without_manual_reactivation(
    download_company, settings
):
    from apps.fiscal.services.scheduling import enqueue_due_downloads

    policy = DownloadPolicy.objects.create(
        company=download_company,
        mode="automatic",
        is_active=True,
        scheduled_time=time(2),
        period_strategy="previous_day",
    )
    now = datetime(2024, 3, 1, 6, tzinfo=UTC)
    settings.ATF_PB_ENABLED = False
    assert enqueue_due_downloads(now=now, dispatch=False) == 0
    policy.refresh_from_db()
    assert policy.is_active
    settings.ATF_PB_ENABLED = True
    assert enqueue_due_downloads(now=now, dispatch=False) == 1
    assert enqueue_due_downloads(now=now, dispatch=False) == 0
    request = download_company.download_requests.get()
    assert request.start_date == date(2024, 2, 29)
    assert request.trigger == "scheduled"


def test_scheduler_recovers_missed_daily_slots_without_duplicate_requests(
    download_company, settings
):
    from apps.fiscal.services.scheduling import enqueue_due_downloads

    settings.ATF_PB_ENABLED = True
    DownloadPolicy.objects.create(
        company=download_company,
        mode="automatic",
        is_active=True,
        scheduled_time=time(2),
        last_scheduled_slot="2026-10-16/daily",
    )
    now = datetime(2026, 10, 20, 6, tzinfo=UTC)
    assert enqueue_due_downloads(now=now, dispatch=False) == 4
    assert set(
        download_company.download_requests.values_list("start_date", flat=True)
    ) == {date(2026, 10, day) for day in (16, 17, 18, 19)}
    assert enqueue_due_downloads(now=now, dispatch=False) == 0


@pytest.mark.parametrize(
    ("frequency", "last_slot", "days", "expected"),
    [
        ("weekly", "2026-10-05/weekly", [0], {date(2026, 10, 11), date(2026, 10, 18)}),
        ("monthly", "2026-08-01/monthly", [], {date(2026, 8, 31), date(2026, 9, 30)}),
    ],
)
def test_scheduler_recovers_weekly_and_monthly_slots(
    download_company, settings, frequency, last_slot, days, expected
):
    from apps.fiscal.services.scheduling import enqueue_due_downloads

    settings.ATF_PB_ENABLED = True
    DownloadPolicy.objects.create(
        company=download_company,
        mode="automatic",
        is_active=True,
        scheduled_time=time(2),
        frequency=frequency,
        weekdays=days,
        last_scheduled_slot=last_slot,
    )
    enqueue_due_downloads(now=datetime(2026, 10, 20, 6, tzinfo=UTC), dispatch=False)
    assert (
        set(download_company.download_requests.values_list("start_date", flat=True))
        == expected
    )


@pytest.mark.django_db(transaction=True)
def test_inactive_schedule_stays_inactive_after_migration(legacy_schema):
    migration = import_module(
        "apps.fiscal.migrations.0010_adapt_programmable_schedules"
    )
    company = _legacy_company(legacy_schema)
    legacy_schema.get_model("fiscal", "SyncPolicy").objects.create(
        company_id=company.pk, mode="automatic", is_active=False, scheduled_time=time(2)
    )
    migration.forwards(legacy_schema, None)
    assert (
        not legacy_schema.get_model("fiscal", "DownloadPolicy")
        .objects.get(company_id=company.pk)
        .is_active
    )
