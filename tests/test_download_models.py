from datetime import date, time

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from apps.organizations.models import AccountingOffice, ClientCompany


@pytest.fixture
def download_company(db):
    office = AccountingOffice.objects.create(
        legal_name="Escritório", tax_identifier="00000000000191"
    )
    return ClientCompany.objects.create(
        office=office, legal_name="Empresa", tax_identifier="00000000000191"
    )


def test_download_policy_keeps_automatic_schedule_fields(download_company):
    from apps.fiscal.models import DownloadPolicy

    policy = DownloadPolicy(
        company=download_company,
        mode="hybrid",
        frequency="weekly",
        scheduled_time=time(3, 45),
        timezone="America/Fortaleza",
        weekdays=[1, 4],
        is_active=True,
        period_strategy="rolling_days",
        rolling_days=7,
    )
    policy.full_clean()
    policy.save()
    policy.refresh_from_db()
    assert policy.mode == "hybrid"
    assert policy.scheduled_time == time(3, 45)
    assert policy.weekdays == [1, 4]
    assert policy.is_active


def test_automatic_policy_requires_schedule(download_company):
    from apps.fiscal.models import DownloadPolicy

    with pytest.raises(ValidationError):
        DownloadPolicy(company=download_company, mode="automatic").full_clean()


def test_duplicate_active_request_is_blocked_but_completed_can_repeat(download_company):
    from apps.fiscal.models import DownloadRequest

    values = dict(
        company=download_company,
        start_date=date(2024, 1, 1),
        end_date=date(2024, 1, 31),
        formats=["xml", "txt"],
        active_key="same-key",
    )
    first = DownloadRequest.objects.create(**values)
    with pytest.raises(IntegrityError), transaction.atomic():
        DownloadRequest.objects.create(**values)
    first.status = "succeeded"
    first.save()
    second = DownloadRequest.objects.create(**values, repeat_of=first)
    assert second.repeat_of_id == first.pk


def test_note_versions_and_events_do_not_compete_for_same_key(download_company):
    from apps.fiscal.models import FiscalEvent, InvoiceDocument, InvoiceXmlVersion

    invoice = InvoiceDocument.objects.create(
        company=download_company, access_key="1" * 44, issued_on=date(2024, 1, 1)
    )
    for digest in ["a" * 64, "b" * 64]:
        InvoiceXmlVersion.objects.create(
            document=invoice, sha256=digest, path=f"xml/{digest}"
        )
    FiscalEvent.objects.create(
        company=download_company,
        access_key=invoice.access_key,
        event_type="110111",
        sequence=1,
        sha256="c" * 64,
        path="events/c.xml",
    )
    assert invoice.versions.count() == 2
    assert FiscalEvent.objects.filter(access_key=invoice.access_key).count() == 1
