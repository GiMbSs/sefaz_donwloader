import hashlib
import io
import zipfile
from datetime import date

import pytest

from apps.fiscal.atf.types import DownloadedArchive, Period

KEY = "24241000000000000191550010000000011000000010"
INVOICE = f"""<nfeProc xmlns="http://www.portalfiscal.inf.br/nfe"><NFe>
<infNFe Id="NFe{KEY}"><ide><mod>55</mod><nNF>1</nNF><tpAmb>1</tpAmb>
<dhEmi>2024-10-10T12:00:00-03:00</dhEmi></ide>
<emit><CNPJ>00000000000191</CNPJ></emit></infNFe></NFe></nfeProc>""".encode()
EVENT = f"""<procEventoNFe xmlns="http://www.portalfiscal.inf.br/nfe"><evento>
<infEvento><chNFe>{KEY}</chNFe><tpAmb>1</tpAmb><tpEvento>210210</tpEvento>
<nSeqEvento>1</nSeqEvento><CNPJ>11111111000111</CNPJ>
<dhEvento>2025-01-02T00:00:00-03:00</dhEvento></infEvento>
</evento></procEventoNFe>""".encode()


def archive_file(tmp_path, entries):
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w", compression=zipfile.ZIP_DEFLATED) as output:
        for name, body in entries:
            output.writestr(name, body)
    payload = data.getvalue()
    path = tmp_path / "download.zip"
    path.write_bytes(payload)
    return DownloadedArchive(
        path, hashlib.sha256(payload).hexdigest(), len(payload), "application/zip"
    )


def test_xml_archive_distinguishes_note_and_recipient_event(tmp_path, download_company):
    from apps.fiscal.services.artifacts import validate_archive

    download = archive_file(tmp_path, [("note.xml", INVOICE), ("event.xml", EVENT)])
    result = validate_archive(
        download,
        company_id=download_company.pk,
        period=Period(date(2024, 10, 1), date(2024, 10, 18)),
        format="xml",
    )
    assert [member.kind for member in result.members] == ["invoice", "event"]
    assert result.members[1].metadata["event_type"] == "210210"
    assert result.members[0].metadata["number"] == "1"


@pytest.mark.parametrize(
    "name,body,allowed",
    [
        ("CHAVES_NAO_ENCONTRADAS.txt", b"", True),
        ("CHAVES_NAO_ENCONTRADAS.txt", b"missing XML", False),
        ("outro.txt", b"", False),
    ],
)
def test_nfce_xml_export_allows_only_known_empty_companion(
    tmp_path, download_company, name, body, allowed
):
    from apps.fiscal.atf.errors import AtfArtifactError
    from apps.fiscal.services.artifacts import validate_archive

    key = KEY[:20] + "65" + KEY[22:]
    invoice = INVOICE.replace(KEY.encode(), key.encode()).replace(
        b"<mod>55", b"<mod>65"
    )
    download = archive_file(tmp_path, [("nota.xml", invoice), (name, body)])
    arguments = dict(
        company_id=download_company.pk,
        period=Period(date(2024, 10, 1), date(2024, 10, 18)),
        format="xml",
        document_model="65",
    )
    if allowed:
        result = validate_archive(download, **arguments)
        assert [member.name for member in result.members] == ["nota.xml"]
        with zipfile.ZipFile(download.staging_path) as archive:
            assert archive.read(name) == body
    else:
        with pytest.raises(AtfArtifactError):
            validate_archive(download, **arguments)


@pytest.mark.parametrize("number", [b"2", b"0", b"abc", b"1000000000"])
def test_invoice_number_must_match_access_key(tmp_path, download_company, number):
    from apps.fiscal.atf.errors import AtfArtifactError
    from apps.fiscal.services.artifacts import validate_archive

    body = INVOICE.replace(b"<nNF>1</nNF>", b"<nNF>" + number + b"</nNF>")
    with pytest.raises(AtfArtifactError):
        validate_archive(
            archive_file(tmp_path, [("note.xml", body)]),
            company_id=download_company.pk,
            period=Period(date(2024, 10, 1), date(2024, 10, 18)),
            format="xml",
        )


@pytest.mark.parametrize(
    "name", ["../note.xml", "/note.xml", "C:\\note.xml", "a/../../note.xml"]
)
def test_zip_member_cannot_escape_storage(tmp_path, download_company, name):
    from apps.fiscal.atf.errors import AtfArtifactError
    from apps.fiscal.services.artifacts import validate_archive

    with pytest.raises(AtfArtifactError):
        validate_archive(
            archive_file(tmp_path, [(name, INVOICE)]),
            company_id=download_company.pk,
            period=Period(date(2024, 10, 1), date(2024, 10, 18)),
            format="xml",
        )


def test_zip_rejects_decompression_over_real_limit(
    tmp_path, download_company, settings
):
    from apps.fiscal.atf.errors import AtfArtifactError
    from apps.fiscal.services.artifacts import validate_archive

    settings.ATF_MAX_UNCOMPRESSED_BYTES = 100
    with pytest.raises(AtfArtifactError):
        validate_archive(
            archive_file(tmp_path, [("note.xml", INVOICE)]),
            company_id=download_company.pk,
            period=Period(date(2024, 10, 1), date(2024, 10, 18)),
            format="xml",
        )


def test_xml_of_another_issuer_is_not_released(tmp_path, download_company):
    from apps.fiscal.atf.errors import AtfIdentityMismatch
    from apps.fiscal.services.artifacts import validate_archive

    other = INVOICE.replace(b"<CNPJ>00000000000191", b"<CNPJ>11111111000111")
    with pytest.raises(AtfIdentityMismatch):
        validate_archive(
            archive_file(tmp_path, [("note.xml", other)]),
            company_id=download_company.pk,
            period=Period(date(2024, 10, 1), date(2024, 10, 18)),
            format="xml",
        )


def test_corrupt_deflate_is_a_classified_artifact_error(tmp_path, download_company):
    from apps.fiscal.atf.errors import AtfArtifactError
    from apps.fiscal.services.artifacts import validate_archive

    download = archive_file(tmp_path, [("note.xml", INVOICE)])
    data = bytearray(download.staging_path.read_bytes())
    with zipfile.ZipFile(download.staging_path) as archive:
        info = archive.infolist()[0]
        offset = info.header_offset + 30 + len(info.filename.encode()) + len(info.extra)
    data[offset] = 0xFF  # Invalid DEFLATE block type, intact central directory.
    download.staging_path.write_bytes(data)
    corrupt = DownloadedArchive(
        download.staging_path,
        hashlib.sha256(data).hexdigest(),
        len(data),
        "application/zip",
    )
    with pytest.raises(AtfArtifactError):
        validate_archive(
            corrupt,
            company_id=download_company.pk,
            period=Period(date(2024, 10, 1), date(2024, 10, 18)),
            format="xml",
        )
