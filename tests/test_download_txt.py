from datetime import date

from apps.fiscal.atf.types import Period
from tests.test_download_archives import archive_file


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
