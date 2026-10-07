import base64
import gzip

import pytest

from apps.fiscal.services.distribution import DistributionParseError, parse_distribution_response


def _doczip(xml: bytes) -> str:
    return base64.b64encode(gzip.compress(xml)).decode("ascii")


def test_parses_official_distribution_envelope_and_decodes_doczip():
    document = b"""<resNFe xmlns=\"http://www.portalfiscal.inf.br/nfe\">
      <chNFe>25010100000000000191550010000000011000000010</chNFe>
      <mod>55</mod>
    </resNFe>"""
    payload = f"""<retDistDFeInt xmlns=\"http://www.portalfiscal.inf.br/nfe\">
      <tpAmb>1</tpAmb><verAplic>SVRS</verAplic><cStat>138</cStat>
      <xMotivo>Documentos localizados</xMotivo>
      <dhResp>2026-10-07T10:00:00-03:00</dhResp>
      <ultNSU>000000000000001</ultNSU><maxNSU>000000000000003</maxNSU>
      <loteDistDFeInt><docZip NSU=\"000000000000001\" schema=\"resNFe_v1.01.xsd\">{_doczip(document)}</docZip></loteDistDFeInt>
    </retDistDFeInt>""".encode()

    result = parse_distribution_response(payload)

    assert result.status_code == "138"
    assert result.returned_last_nsu == "000000000000001"
    assert result.returned_max_nsu == "000000000000003"
    assert len(result.documents) == 1
    assert result.documents[0].schema_name == "resNFe_v1.01.xsd"
    assert result.documents[0].xml_payload == document


@pytest.mark.parametrize(
    "payload",
    [
        b"<!DOCTYPE response [<!ENTITY dangerous SYSTEM 'file:///etc/passwd'>]><retDistDFeInt/>",
        b"<retDistDFeInt><cStat>138</cStat><docZip NSU='001' schema='x'>not-base64</docZip></retDistDFeInt>",
    ],
)
def test_rejects_unsafe_or_malformed_distribution_payloads(payload):
    with pytest.raises(DistributionParseError):
        parse_distribution_response(payload)
