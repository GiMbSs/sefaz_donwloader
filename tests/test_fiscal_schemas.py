import hashlib
from pathlib import Path

import pytest

from apps.fiscal.services.schemas import FiscalSchemaError, validate_fiscal_xml


def _distribution_request(cnpj: str = "00000000000191") -> bytes:
    return f"""<distDFeInt xmlns="http://www.portalfiscal.inf.br/nfe" versao="1.01">
      <tpAmb>2</tpAmb><CNPJ>{cnpj}</CNPJ>
      <distNSU><ultNSU>000000000000000</ultNSU></distNSU>
    </distDFeInt>""".encode()


def test_distribution_xsd_accepts_alphanumeric_cnpj_and_rejects_wrong_root():
    root = validate_fiscal_xml(
        _distribution_request("12ABC34501DE35"),
        expected_root="distDFeInt",
    )

    assert root.tag == "{http://www.portalfiscal.inf.br/nfe}distDFeInt"
    with pytest.raises(FiscalSchemaError):
        validate_fiscal_xml(_distribution_request(), expected_root="retDistDFeInt")


def test_vendored_distribution_schemas_match_the_manifest(settings):
    manifest = settings.FISCAL_SCHEMA_ROOT / "SHA256SUMS"
    expected_paths: set[Path] = set()
    for line in manifest.read_text(encoding="utf-8").splitlines():
        expected_hash, relative_name = line.split("  ", 1)
        path = settings.FISCAL_SCHEMA_ROOT / relative_name
        expected_paths.add(path)
        assert hashlib.sha256(path.read_bytes()).hexdigest() == expected_hash

    assert expected_paths == set(
        (settings.FISCAL_SCHEMA_ROOT / "distribuicao").glob("*.xsd")
    )
