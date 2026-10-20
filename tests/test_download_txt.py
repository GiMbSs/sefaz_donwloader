from datetime import date

import pytest

from apps.fiscal.atf.types import Period
from tests.test_download_archives import archive_file


@pytest.mark.parametrize("document_model", ["55", "65"])
def test_txt_accepts_formatted_issuer_cnpj_without_changing_original_bytes(
    tmp_path, download_company, document_model
):
    import hashlib

    from apps.fiscal.services.artifacts import validate_archive
    from tests.test_download_archives import KEY

    key = KEY[:20] + document_model + KEY[22:]
    content = (
        "Chave_de_acesso|Numero|Data_de_emissao|CPF_CNPJ_emit\n"
        f"{key}|1|10/10/2024|00.000.000/0001-91\n"
    ).encode()
    archive = archive_file(tmp_path, [("report.txt", content)])
    validation = validate_archive(
        archive,
        company_id=download_company.pk,
        period=Period(date(2024, 10, 1), date(2024, 10, 31)),
        format="txt",
        document_model=document_model,
    )
    assert validation.members[0].metadata["invoice_count"] == "1"
    assert validation.members[0].sha256 == hashlib.sha256(content).hexdigest()


@pytest.mark.parametrize(
    ("issuer", "key_model", "key_cnpj", "expected_code"),
    [
        ("11.222.333/0001-81", "55", "00000000000191", "atf_txt_issuer_mismatch"),
        ("00.000.000/0001-91", "55", "11222333000181", "atf_txt_key_issuer_mismatch"),
        ("00.000.000/0001-91", "65", "00000000000191", "atf_txt_model_mismatch"),
    ],
)
def test_txt_normalization_still_rejects_other_issuer_or_document_model(
    tmp_path, download_company, issuer, key_model, key_cnpj, expected_code
):
    from apps.fiscal.atf.errors import AtfIdentityMismatch
    from apps.fiscal.services.artifacts import validate_archive
    from tests.test_download_archives import KEY

    key = KEY[:6] + key_cnpj + key_model + KEY[22:]
    content = (
        "Chave_de_acesso|Numero|Data_de_emissao|CPF_CNPJ_emit\n"
        f"{key}|1|10/10/2024|{issuer}\n"
    ).encode()
    with pytest.raises(AtfIdentityMismatch) as error:
        validate_archive(
            archive_file(tmp_path, [("report.txt", content)]),
            company_id=download_company.pk,
            period=Period(date(2024, 10, 1), date(2024, 10, 31)),
            format="txt",
        )
    assert str(error.value) == expected_code


def test_txt_preserves_windows_1252_without_requiring_xml(tmp_path, download_company):
    from apps.fiscal.services.artifacts import validate_archive
    from tests.test_download_archives import KEY

    content = (
        "Chave_de_acesso|Numero|Data_de_emissao|CPF_CNPJ_emit|Descricao\n"
        f"{KEY}|1|10/10/2024|00000000000191|Pão\n"
    ).encode("cp1252")
    archive = archive_file(tmp_path, [("report.txt", content)])
    validation = validate_archive(
        archive,
        company_id=download_company.pk,
        period=Period(date(2024, 10, 1), date(2024, 10, 31)),
        format="txt",
    )
    assert validation.members[0].metadata["encoding"] == "cp1252"
    assert validation.members[0].sha256


def test_txt_of_another_company_is_rejected(tmp_path, download_company):
    import pytest

    from apps.fiscal.atf.errors import AtfIdentityMismatch
    from apps.fiscal.services.artifacts import validate_archive
    from tests.test_download_archives import KEY

    content = (
        "Chave_de_acesso|Numero|Data_de_emissao|CPF_CNPJ_emit\n"
        f"{KEY}|1|10/10/2024|11222333000181\n"
    ).encode()
    with pytest.raises(AtfIdentityMismatch):
        validate_archive(
            archive_file(tmp_path, [("report.txt", content)]),
            company_id=download_company.pk,
            period=Period(date(2024, 10, 1), date(2024, 10, 31)),
            format="txt",
        )


@pytest.mark.parametrize(
    ("issued", "expected_code"),
    [
        ("2024-10-10 12:30:00", None),
        ("2024-11-10 12:30:00", "atf_txt_outside_period"),
        ("2024-02-30 12:30:00", "atf_txt_date_invalid"),
    ],
)
def test_nfce_txt_timestamp_is_checked_against_requested_period(
    tmp_path, download_company, issued, expected_code
):
    from apps.fiscal.atf.errors import AtfArtifactError
    from apps.fiscal.services.artifacts import validate_archive
    from tests.test_download_archives import KEY

    key = KEY[:20] + "65" + KEY[22:]
    content = (
        "Chave_de_acesso|Numero|Data_de_emissao|CPF_CNPJ_emit\n"
        f"{key}|1|{issued}|00.000.000/0001-91\n"
    ).encode()
    arguments = dict(
        company_id=download_company.pk,
        period=Period(date(2024, 10, 1), date(2024, 10, 31)),
        format="txt",
        document_model="65",
    )
    archive = archive_file(tmp_path, [("report.txt", content)])
    if expected_code:
        with pytest.raises(AtfArtifactError) as error:
            validate_archive(archive, **arguments)
        assert str(error.value) == expected_code
    else:
        validation = validate_archive(archive, **arguments)
        assert validation.members[0].metadata["invoice_count"] == "1"
