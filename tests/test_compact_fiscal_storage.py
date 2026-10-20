import hashlib
from datetime import date
from pathlib import Path
from uuid import uuid4

import pytest
from django.urls import reverse

from apps.fiscal.atf.types import AttachmentRef, Period
from tests.test_download_archives import INVOICE, KEY, archive_file
from tests.test_nfce_downloads import NFCE_XML


@pytest.fixture
def save_archive(tmp_path, settings):
    from apps.fiscal.models import DownloadPart, DownloadRequest
    from apps.fiscal.services.artifacts import persist_archive, validate_archive
    from apps.fiscal.services.documents import index_archive

    settings.FISCAL_NOTES_ROOT = tmp_path / "notes"

    def save(
        company,
        *,
        model="55",
        format="xml",
        requested_on=date(2026, 10, 20),
        body=None,
        index=True,
        filename=None,
    ):
        period = Period(date(2024, 10, 1), date(2024, 10, 18))
        if body is None:
            key = KEY if model == "55" else KEY[:20] + "65" + KEY[22:]
            body = (
                (INVOICE if model == "55" else NFCE_XML)
                if format == "xml"
                else (
                    "Chave_de_acesso|Numero|Data_de_emissao|CPF_CNPJ_emit\n"
                    f"{key}|1|10/10/2024|00000000000191\n"
                ).encode()
            )
        request = DownloadRequest.objects.create(
            company=company,
            document_model=model,
            start_date=period.start,
            end_date=period.end,
            requested_on=requested_on,
            formats=[format],
            active_key=uuid4().hex,
        )
        part = DownloadPart.objects.create(
            request=request,
            start_date=period.start,
            end_date=period.end,
            format=format,
            remote_account_key="a" * 64,
        )
        download = archive_file(tmp_path, [(f"note.{format}", body)])
        if filename is not None:
            from dataclasses import replace

            download = replace(download, filename=filename)
        original = download.staging_path.read_bytes()
        validation = validate_archive(
            download,
            company_id=company.pk,
            period=period,
            format=format,
            document_model=model,
        )
        archive = persist_archive(
            part.pk, AttachmentRef(uuid4().hex, 0), download, validation
        )
        if index:
            index_archive(archive.pk)
        return archive, original, body

    return save


@pytest.mark.parametrize(("model", "folder"), [("55", "NFe"), ("65", "NFCe")])
@pytest.mark.parametrize("format", ["xml", "txt"])
@pytest.mark.parametrize("requested_on", [date(2026, 10, 20), date(2024, 11, 2)])
def test_files_are_flat_under_model_format_and_original_request_date(
    download_company, save_archive, settings, model, folder, format, requested_on
):
    archive, original, body = save_archive(
        download_company, model=model, format=format, requested_on=requested_on
    )
    expected = (
        Path("00000000000191/00000000000191")
        / folder
        / format.upper()
        / str(requested_on)
    )
    member = archive.members.get()
    assert Path(archive.path).parent == expected
    assert Path(member.path).parent == expected
    assert (settings.FISCAL_NOTES_ROOT / archive.path).read_bytes() == original
    assert (settings.FISCAL_NOTES_ROOT / member.path).read_bytes() == body
    assert {p.name for p in (settings.FISCAL_NOTES_ROOT / expected).iterdir()} == {
        Path(archive.path).name,
        Path(member.path).name,
    }


def test_distinct_versions_of_same_note_are_preserved_in_same_day(
    download_company, save_archive, settings
):
    from apps.fiscal.models import InvoiceDocument

    first, _, first_body = save_archive(download_company)
    second, _, second_body = save_archive(download_company, body=INVOICE + b"\n")
    first_path, second_path = first.members.get().path, second.members.get().path
    assert Path(first_path).parent == Path(second_path).parent
    assert first_path != second_path
    assert (settings.FISCAL_NOTES_ROOT / first_path).read_bytes() == first_body
    assert (settings.FISCAL_NOTES_ROOT / second_path).read_bytes() == second_body
    assert InvoiceDocument.objects.get(company=download_company).versions.count() == 2


def test_same_company_cnpj_in_different_offices_has_separate_files(
    download_company, save_archive, settings
):
    from apps.organizations.models import AccountingOffice, ClientCompany

    other_office = AccountingOffice.objects.create(
        legal_name="Other", tax_identifier="11222333000181"
    )
    other_company = ClientCompany.objects.create(
        office=other_office,
        legal_name="Same CNPJ",
        tax_identifier=download_company.tax_identifier,
    )
    first, _, _ = save_archive(download_company)
    second, _, _ = save_archive(other_company)
    assert Path(first.path).parts[0] == "00000000000191"
    assert Path(second.path).parts[0] == "11222333000181"
    assert first.path != second.path
    assert (settings.FISCAL_NOTES_ROOT / first.path).is_file()
    assert (settings.FISCAL_NOTES_ROOT / second.path).is_file()


def test_legacy_archive_and_member_paths_remain_readable_when_reindexed(
    download_company, download_actor, save_archive, settings, client
):
    from apps.fiscal.models import ArchiveMember, InvoiceXmlVersion
    from apps.fiscal.services.documents import index_archive
    from apps.fiscal.services.storage import FiscalStorage

    archive, original, body = save_archive(download_company, index=False)
    storage = FiscalStorage()
    old_zip = Path(
        "escritorios/escritorio_00000000000191/empresas/00000000000191/XML/2024/11/02/pedido/parte/original.zip"
    )
    old_member = old_zip.parent / "membros" / "legacy.xml"
    storage._write(old_zip, original)
    storage._write(old_member, body)
    storage.delete(archive.path)
    archive.path = str(old_zip)
    archive.save(update_fields=["path"])
    member = ArchiveMember.objects.create(
        archive=archive,
        name="note.xml",
        kind="invoice",
        path=str(old_member),
        sha256=hashlib.sha256(body).hexdigest(),
        byte_count=len(body),
    )
    before = {p for p in settings.FISCAL_NOTES_ROOT.rglob("*") if p.is_file()}
    index_archive(archive.pk)
    index_archive(archive.pk)
    member.refresh_from_db()
    assert member.path == str(old_member)
    assert InvoiceXmlVersion.objects.get().path == str(old_member)
    assert {p for p in settings.FISCAL_NOTES_ROOT.rglob("*") if p.is_file()} == before
    client.force_login(download_actor)
    response = client.get(reverse("download-archive", args=[archive.pk]))
    assert response.status_code == 200
    assert b"".join(response.streaming_content) == original
    response.close()


@pytest.mark.parametrize("model", ["55", "65"])
@pytest.mark.parametrize("format", ["xml", "txt"])
def test_sefaz_zip_name_is_preserved_on_disk_and_interface(
    download_company, download_actor, save_archive, settings, client, model, format
):
    name = f"Consulta_{model}_{format}_01-10-2024_18-10-2024.zip"
    archive, original, _ = save_archive(
        download_company, model=model, format=format, filename=name
    )
    assert Path(archive.path).name == name
    assert archive.filename == name
    assert (settings.FISCAL_NOTES_ROOT / archive.path).read_bytes() == original
    client.force_login(download_actor)
    response = client.get(reverse("download-archive", args=[archive.pk]))
    assert response.status_code == 200
    assert name in response.headers["Content-Disposition"]
    assert b"".join(response.streaming_content) == original
    response.close()


def test_different_zip_contents_with_same_original_name_are_not_overwritten(
    download_company, save_archive, settings
):
    name = "Consulta_01-10-2024_18-10-2024.zip"
    first, first_bytes, _ = save_archive(download_company, filename=name)
    second, second_bytes, _ = save_archive(
        download_company, filename=name, body=INVOICE + b"\n"
    )
    assert first.path != second.path
    assert Path(first.path).name == Path(second.path).name == name
    assert first.filename == second.filename == name
    assert (settings.FISCAL_NOTES_ROOT / first.path).read_bytes() == first_bytes
    assert (settings.FISCAL_NOTES_ROOT / second.path).read_bytes() == second_bytes


def test_identical_zip_with_same_name_reuses_original_file(
    download_company, save_archive, settings
):
    from apps.fiscal.atf.types import DownloadedArchive
    from apps.fiscal.services.artifacts import persist_archive, validate_archive

    name = "Consulta_01-10-2024_18-10-2024.zip"
    first, original, _ = save_archive(download_company, filename=name)
    download = DownloadedArchive(
        settings.FISCAL_NOTES_ROOT / first.path,
        first.sha256,
        first.byte_count,
        "application/zip",
        filename=name,
    )
    validation = validate_archive(
        download,
        company_id=download_company.pk,
        period=Period(date(2024, 10, 1), date(2024, 10, 18)),
        format="xml",
    )
    second = persist_archive(
        first.part_id, AttachmentRef(uuid4().hex, 0), download, validation
    )
    assert second.path == first.path
    assert (settings.FISCAL_NOTES_ROOT / first.path).read_bytes() == original


def test_concurrent_original_name_collision_does_not_replace_other_file(
    download_company, save_archive, settings, monkeypatch
):
    import os

    link = os.link
    name = "Consulta_01-10-2024_18-10-2024.zip"

    def competing_publication(source, target):
        if target.name == name and target.parent.name == "2026-10-20":
            target.write_bytes(b"another publication")
            raise FileExistsError()
        return link(source, target)

    monkeypatch.setattr("apps.fiscal.services.artifacts.os.link", competing_publication)
    archive, original, _ = save_archive(download_company, filename=name)
    root = (
        settings.FISCAL_NOTES_ROOT / "00000000000191/00000000000191/NFe/XML/2026-10-20"
    )
    assert (root / name).read_bytes() == b"another publication"
    assert Path(archive.path).name == name
    assert (settings.FISCAL_NOTES_ROOT / archive.path).read_bytes() == original
