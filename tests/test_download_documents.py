from datetime import date

from apps.fiscal.atf.types import AttachmentRef, Period
from tests.test_download_archives import EVENT, INVOICE, archive_file


def test_archived_note_and_event_are_indexed_idempotently(
    tmp_path, download_company, settings
):
    from apps.fiscal.models import (
        DownloadPart,
        DownloadRequest,
        FiscalEvent,
        InvoiceDocument,
    )
    from apps.fiscal.services.artifacts import persist_archive, validate_archive
    from apps.fiscal.services.documents import index_archive

    settings.FISCAL_NOTES_ROOT = tmp_path / "notes"
    period = Period(date(2024, 10, 1), date(2024, 10, 18))
    request = DownloadRequest.objects.create(
        company=download_company,
        start_date=period.start,
        end_date=period.end,
        formats=["xml"],
        active_key="index",
    )
    part = DownloadPart.objects.create(
        request=request,
        start_date=period.start,
        end_date=period.end,
        format="xml",
        remote_account_key="a" * 64,
    )
    download = archive_file(tmp_path, [("note.xml", INVOICE), ("event.xml", EVENT)])
    validated = validate_archive(
        download, company_id=download_company.pk, period=period, format="xml"
    )
    archive = persist_archive(part.pk, AttachmentRef("10", 0), download, validated)
    index_archive(archive.pk)
    index_archive(archive.pk)
    assert InvoiceDocument.objects.filter(company=download_company).count() == 1
    assert FiscalEvent.objects.filter(company=download_company).count() == 1
    assert archive.members.count() == 2
    assert archive.path.endswith(".zip")
    assert InvoiceDocument.objects.get(company=download_company).number == 1
    expected = (
        f"{download_company.office.tax_identifier}/"
        f"{download_company.tax_identifier}/NFe/XML/"
        f"{request.requested_on:%Y-%m-%d}/"
    )
    assert expected in archive.path
    assert all(expected in member.path for member in archive.members.all())
