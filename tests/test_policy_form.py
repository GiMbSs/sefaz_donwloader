from datetime import UTC, datetime, time

import pytest
from django.urls import reverse
from lxml import html

from apps.fiscal.models import DownloadPolicy
from apps.operations.download_forms import DownloadPolicyForm
from apps.organizations.models import OfficeMembership


def policy_data(**updates):
    values = {
        "mode": "automatic",
        "frequency": "daily",
        "scheduled_time": "02:00",
        "timezone": "America/Fortaleza",
        "period_strategy": "previous_day",
        "formats": ["xml", "txt"],
        "document_models": ["55"],
        "is_active": "on",
    }
    values.update(updates)
    return values


@pytest.mark.parametrize("frequency", ["daily", "weekly", "monthly"])
@pytest.mark.parametrize("strategy", ["previous_day", "previous_month", "rolling_days"])
def test_policy_requires_only_fields_for_selected_frequency_and_period(
    download_company, frequency, strategy
):
    data = policy_data(frequency=frequency, period_strategy=strategy)
    if frequency == "weekly":
        data["weekdays"] = ["1", "4"]
    if frequency == "monthly":
        data["monthday"] = "5"
    if strategy == "rolling_days":
        data["rolling_days"] = "7"
    form = DownloadPolicyForm(data, instance=DownloadPolicy(company=download_company))
    assert form.is_valid(), form.errors
    policy = form.save()
    assert policy.frequency == frequency
    assert policy.period_strategy == strategy


def test_hidden_irrelevant_values_do_not_block_save_or_erase_existing_choices(
    download_company,
):
    policy = DownloadPolicy.objects.create(
        company=download_company, monthday=31, rolling_days=14, weekdays=[1, 4]
    )
    form = DownloadPolicyForm(
        policy_data(monthday="invalid", rolling_days="invalid", weekdays=["invalid"]),
        instance=policy,
    )
    assert form.is_valid(), form.errors
    policy = form.save()
    assert policy.monthday == 31
    assert policy.rolling_days == 14
    assert policy.weekdays == [1, 4]


@pytest.mark.parametrize(
    ("updates", "field"),
    [
        ({"frequency": "weekly"}, "weekdays"),
        ({"frequency": "monthly"}, "monthday"),
        ({"period_strategy": "rolling_days"}, "rolling_days"),
        ({"scheduled_time": ""}, "scheduled_time"),
    ],
)
def test_relevant_schedule_fields_still_require_valid_values(
    download_company, updates, field
):
    form = DownloadPolicyForm(
        policy_data(**updates), instance=DownloadPolicy(company=download_company)
    )
    assert not form.is_valid()
    assert field in form.errors


def test_switching_to_manual_pauses_execution_and_keeps_schedule_configuration(
    download_company,
):
    policy = DownloadPolicy.objects.create(
        company=download_company,
        mode="hybrid",
        is_active=True,
        frequency="weekly",
        scheduled_time=time(2),
        weekdays=[1, 4],
        monthday=31,
        rolling_days=14,
    )
    form = DownloadPolicyForm({"mode": "manual", "is_active": "on"}, instance=policy)
    assert form.is_valid(), form.errors
    policy = form.save()
    assert policy.mode == "manual"
    assert not policy.is_active
    assert policy.frequency == "weekly" and policy.weekdays == [1, 4]
    assert policy.monthday == 31 and policy.rolling_days == 14
    assert policy.scheduled_time == time(2)
    assert policy.formats == ["xml", "txt"]


def test_monthly_example_saves_without_unused_fields_and_schedules_previous_month(
    download_company, settings
):
    from apps.fiscal.services.scheduling import enqueue_due_downloads

    form = DownloadPolicyForm(
        policy_data(
            frequency="monthly", monthday="5", period_strategy="previous_month"
        ),
        instance=DownloadPolicy(company=download_company),
    )
    assert form.is_valid(), form.errors
    form.save()
    settings.ATF_PB_ENABLED = True
    assert (
        enqueue_due_downloads(now=datetime(2026, 10, 5, 6, tzinfo=UTC), dispatch=False)
        == 1
    )
    request = download_company.download_requests.get()
    assert request.start_date.isoformat() == "2026-09-01"
    assert request.end_date.isoformat() == "2026-09-30"


def test_policy_page_groups_timing_period_and_files_and_has_static_help(
    client, download_company, download_actor
):
    OfficeMembership.objects.filter(user=download_actor).update(role="admin")
    client.force_login(download_actor)
    response = client.get(reverse("company-policy", args=[download_company.pk]))
    assert response.status_code == 200
    page = html.fromstring(response.content)
    assert page.xpath(
        '//fieldset[legend[contains(., "Quando executar")]]//select[@name="frequency"]'
    )
    assert page.xpath(
        '//fieldset[legend[contains(., "Quais notas consultar")]]'
        '//select[@name="period_strategy"]'
    )
    assert page.xpath(
        '//fieldset[legend[contains(., "Quais arquivos baixar")]]'
        '//input[@name="formats"]'
    )
    assert page.xpath('//aside[@aria-labelledby="schedule-help-title"]')
    assert "01/09 a 30/09" in page.text_content()
