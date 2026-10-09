from types import SimpleNamespace
from typing import cast

import pytest
from lxml import etree

from apps.certificates.models import DigitalCertificate
from apps.certificates.services.vault import CertificateVault
from apps.fiscal.services.sefaz import (
    NFE_NAMESPACE,
    SOAP12_NAMESPACE,
    WSDL_NAMESPACE,
    NfeDistributionClient,
    SefazDistributionError,
    build_dist_nsu_xml,
    build_soap_envelope,
    endpoint_for,
    extract_distribution_response,
)


def _soap_response(*, environment: str = "2") -> bytes:
    return f"""<?xml version="1.0" encoding="utf-8"?>
    <soap12:Envelope xmlns:soap12="{SOAP12_NAMESPACE}">
      <soap12:Body>
        <nfeDistDFeInteresseResponse xmlns="{WSDL_NAMESPACE}">
          <nfeDistDFeInteresseResult>
            <retDistDFeInt xmlns="{NFE_NAMESPACE}" versao="1.01">
              <tpAmb>{environment}</tpAmb><verAplic>TESTE</verAplic>
              <cStat>137</cStat><xMotivo>Sem novos documentos</xMotivo>
              <dhResp>2026-10-07T10:00:00-03:00</dhResp>
              <ultNSU>000000000000000</ultNSU><maxNSU>000000000000000</maxNSU>
            </retDistDFeInt>
          </nfeDistDFeInteresseResult>
        </nfeDistDFeInteresseResponse>
      </soap12:Body>
    </soap12:Envelope>""".encode()


class _Transport:
    def __init__(self, response: bytes) -> None:
        self.response = response
        self.calls: list[dict[str, object]] = []

    def post(self, **kwargs: object) -> bytes:
        self.calls.append(kwargs)
        return self.response


@pytest.mark.parametrize(
    ("environment", "expected_environment_code", "expected_endpoint_prefix"),
    [
        ("production", "1", "https://www1.nfe.fazenda.gov.br/"),
        ("homologation", "2", "https://hom.nfe.fazenda.gov.br/"),
    ],
)
def test_request_uses_the_selected_environment_in_xml_and_endpoint(
    environment: str,
    expected_environment_code: str,
    expected_endpoint_prefix: str,
):
    request = build_dist_nsu_xml(
        tax_identifier="12ABC34501DE35",
        environment=environment,
        last_nsu="42",
    )
    soap = build_soap_envelope(request)
    root = etree.fromstring(soap)
    namespaces = {
        "soap12": SOAP12_NAMESPACE,
        "wsdl": WSDL_NAMESPACE,
        "nfe": NFE_NAMESPACE,
    }

    assert root.xpath("string(.//wsdl:versaoDados)", namespaces=namespaces) == "1.01"
    assert root.xpath("string(.//wsdl:cUF)", namespaces=namespaces) == "91"
    assert (
        root.xpath("string(.//nfe:tpAmb)", namespaces=namespaces)
        == expected_environment_code
    )
    assert root.xpath("string(.//nfe:CNPJ)", namespaces=namespaces) == "12ABC34501DE35"
    assert (
        root.xpath("string(.//nfe:ultNSU)", namespaces=namespaces)
        == "000000000000042"
    )
    assert endpoint_for(environment).startswith(expected_endpoint_prefix)


def test_client_extracts_and_validates_the_inner_distribution_response():
    transport = _Transport(_soap_response())
    client = NfeDistributionClient(transport=transport)
    certificate = cast(DigitalCertificate, SimpleNamespace())
    vault = cast(CertificateVault, SimpleNamespace())

    result = client.request_dist_nsu(
        tax_identifier="00000000000191",
        environment="homologation",
        last_nsu="",
        certificate=certificate,
        vault=vault,
    )

    assert result.endpoint.startswith("https://hom.nfe.fazenda.gov.br/")
    assert b"retDistDFeInt" in result.distribution_response
    assert len(transport.calls) == 1


def test_rejects_soap_fault_or_unvalidated_inner_response():
    fault = f"""<soap12:Envelope xmlns:soap12="{SOAP12_NAMESPACE}">
      <soap12:Body><soap12:Fault><soap12:Reason /></soap12:Fault></soap12:Body>
    </soap12:Envelope>""".encode()

    with pytest.raises(SefazDistributionError):
        extract_distribution_response(fault)
