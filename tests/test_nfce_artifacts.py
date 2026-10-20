from datetime import date

import pytest

from apps.fiscal.atf.types import Period
from tests.test_download_archives import INVOICE, KEY, archive_file
from tests.test_nfce_downloads import NFCE_KEY, NFCE_XML


@pytest.mark.parametrize("format", ["xml", "txt"])
def test_nfce_archive_checks_model_and_collects_invoice_number(
    tmp_path, download_company, format
):
    from apps.fiscal.services.artifacts import validate_archive

    body = (
        NFCE_XML
        if format == "xml"
        else (
            "Chave_de_acesso|Numero|Data_de_emissao|CPF_CNPJ_emit\n"
            f"{NFCE_KEY}|1|10/10/2024|00000000000191\n"
        ).encode()
    )
    result = validate_archive(
        archive_file(tmp_path, [(f"note.{format}", body)]),
        company_id=download_company.pk,
        period=Period(date(2024, 10, 10), date(2024, 10, 10)),
        format=format,
        document_model="65",
    )
    if format == "xml":
        assert result.members[0].metadata["model"] == "65"
        assert result.members[0].metadata["number"] == "1"
    else:
        assert result.members[0].metadata["invoice_count"] == "1"


@pytest.mark.parametrize(("requested", "actual"), [("55", "65"), ("65", "55")])
@pytest.mark.parametrize("format", ["xml", "txt"])
def test_wrong_model_archive_is_not_published(
    tmp_path, download_company, requested, actual, format
):
    from apps.fiscal.atf.errors import AtfError
    from apps.fiscal.services.artifacts import validate_archive

    key = NFCE_KEY if actual == "65" else KEY
    body = (
        (NFCE_XML if actual == "65" else INVOICE)
        if format == "xml"
        else (
            "Chave_de_acesso|Numero|Data_de_emissao|CPF_CNPJ_emit\n"
            f"{key}|1|10/10/2024|00000000000191\n"
        ).encode()
    )
    with pytest.raises(AtfError):
        validate_archive(
            archive_file(tmp_path, [(f"note.{format}", body)]),
            company_id=download_company.pk,
            period=Period(date(2024, 10, 10), date(2024, 10, 10)),
            format=format,
            document_model=requested,
        )
