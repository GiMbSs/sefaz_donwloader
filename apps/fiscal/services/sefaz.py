"""NFeDistribuicaoDFe SOAP 1.2 client isolated to the worker boundary."""

from __future__ import annotations

import os
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

import requests
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.serialization import pkcs12
from django.conf import settings
from django.core.exceptions import ValidationError
from lxml import etree

from apps.certificates.services.vault import CertificateVault, CertificateVaultError
from apps.fiscal.services.schemas import FiscalSchemaError, validate_fiscal_xml
from apps.organizations.validators import (
    normalize_tax_identifier,
    validate_tax_identifier,
)

if TYPE_CHECKING:
    from apps.certificates.models import DigitalCertificate


NFE_NAMESPACE = "http://www.portalfiscal.inf.br/nfe"
SOAP12_NAMESPACE = "http://www.w3.org/2003/05/soap-envelope"
WSDL_NAMESPACE = "http://www.portalfiscal.inf.br/nfe/wsdl/NFeDistribuicaoDFe"
SOAP_ACTION = f"{WSDL_NAMESPACE}/nfeDistDFeInteresse"
_ENDPOINTS = {
    "production": (
        "https://www1.nfe.fazenda.gov.br/NFeDistribuicaoDFe/"
        "NFeDistribuicaoDFe.asmx"
    ),
    "homologation": (
        "https://hom.nfe.fazenda.gov.br/NFeDistribuicaoDFe/"
        "NFeDistribuicaoDFe.asmx"
    ),
}


class SefazDistributionError(RuntimeError):
    """The distribution request cannot safely proceed or be trusted."""


class SefazTransportError(SefazDistributionError):
    """Mutual-TLS transport to SEFAZ did not return a usable SOAP response."""


@dataclass(frozen=True)
class SefazDistributionResult:
    endpoint: str
    soap_response: bytes
    distribution_response: bytes


class SoapTransport(Protocol):
    def post(
        self,
        *,
        endpoint: str,
        envelope: bytes,
        certificate: DigitalCertificate,
        vault: CertificateVault,
    ) -> bytes:
        """Send one SOAP envelope with the company's A1 certificate."""


class MutualTlsSoapTransport:
    """HTTPS transport that materializes A1 PEM files only for one request."""

    def post(
        self,
        *,
        endpoint: str,
        envelope: bytes,
        certificate: DigitalCertificate,
        vault: CertificateVault,
    ) -> bytes:
        try:
            pfx_payload = vault.load(certificate)
            password = vault.unseal_password(certificate)
        except CertificateVaultError as error:
            raise SefazTransportError(
                "O certificado ativo não pôde ser aberto pelo worker."
            ) from error
        try:
            with _temporary_client_certificate(pfx_payload, password) as client_cert:
                return self._post(
                    endpoint=endpoint,
                    envelope=envelope,
                    client_cert=client_cert,
                )
        finally:
            pfx_payload = b""
            password = ""

    @staticmethod
    def _post(*, endpoint: str, envelope: bytes, client_cert: tuple[str, str]) -> bytes:
        verify: bool | str = settings.SEFAZ_TLS_CA_BUNDLE or True
        headers = {
            "Accept": "application/soap+xml, text/xml, application/xml",
            "Content-Type": (
                "application/soap+xml; charset=utf-8; "
                f'action="{SOAP_ACTION}"'
            ),
            "SOAPAction": f'"{SOAP_ACTION}"',
        }
        try:
            with requests.post(
                endpoint,
                data=envelope,
                headers=headers,
                cert=client_cert,
                verify=verify,
                timeout=(
                    settings.SEFAZ_CONNECT_TIMEOUT_SECONDS,
                    settings.SEFAZ_READ_TIMEOUT_SECONDS,
                ),
                allow_redirects=False,
                stream=True,
            ) as response:
                if response.status_code != 200:
                    raise SefazTransportError(
                        "A SEFAZ respondeu com um status HTTP inesperado."
                    )
                return _read_bounded_response(response)
        except requests.RequestException as error:
            raise SefazTransportError(
                "Não foi possível estabelecer uma conexão mTLS com a SEFAZ."
            ) from error


class NfeDistributionClient:
    """Build, validate, send, and unwrap a single ``distNSU`` consultation."""

    def __init__(self, transport: SoapTransport | None = None) -> None:
        self.transport = transport or MutualTlsSoapTransport()

    def request_dist_nsu(
        self,
        *,
        tax_identifier: str,
        environment: str,
        last_nsu: str,
        certificate: DigitalCertificate,
        vault: CertificateVault | None = None,
    ) -> SefazDistributionResult:
        endpoint = endpoint_for(environment)
        request_xml = build_dist_nsu_xml(
            tax_identifier=tax_identifier,
            environment=environment,
            last_nsu=last_nsu,
        )
        envelope = build_soap_envelope(request_xml)
        raw_response = self.transport.post(
            endpoint=endpoint,
            envelope=envelope,
            certificate=certificate,
            vault=vault or CertificateVault(),
        )
        return SefazDistributionResult(
            endpoint=endpoint,
            soap_response=raw_response,
            distribution_response=extract_distribution_response(raw_response),
        )


def endpoint_for(environment: str) -> str:
    try:
        return _ENDPOINTS[environment]
    except KeyError as error:
        raise SefazDistributionError(
            "Ambiente fiscal inválido para distribuição."
        ) from error


def build_dist_nsu_xml(
    *,
    tax_identifier: str,
    environment: str,
    last_nsu: str,
) -> bytes:
    """Build the signed-contract request body; distribution itself has no XMLDSig."""
    try:
        validate_tax_identifier(tax_identifier)
    except ValidationError as error:
        raise SefazDistributionError("O CNPJ da empresa é inválido.") from error
    nsu = _normalise_nsu(last_nsu)
    environment_code = _environment_code(environment)
    root = etree.Element(
        etree.QName(NFE_NAMESPACE, "distDFeInt"),
        nsmap={None: NFE_NAMESPACE},
        versao="1.01",
    )
    etree.SubElement(root, etree.QName(NFE_NAMESPACE, "tpAmb")).text = environment_code
    etree.SubElement(root, etree.QName(NFE_NAMESPACE, "CNPJ")).text = (
        normalize_tax_identifier(tax_identifier)
    )
    dist_nsu = etree.SubElement(root, etree.QName(NFE_NAMESPACE, "distNSU"))
    etree.SubElement(dist_nsu, etree.QName(NFE_NAMESPACE, "ultNSU")).text = nsu
    payload = etree.tostring(root, encoding="utf-8", xml_declaration=True)
    try:
        validate_fiscal_xml(payload, expected_root="distDFeInt")
    except FiscalSchemaError as error:
        raise SefazDistributionError(
            "A solicitação não atende ao schema da distribuição."
        ) from error
    return payload


def build_soap_envelope(distribution_request: bytes) -> bytes:
    """Wrap a schema-validated request in the official SOAP 1.2 operation."""
    try:
        request_root = validate_fiscal_xml(
            distribution_request,
            expected_root="distDFeInt",
        )
    except FiscalSchemaError as error:
        raise SefazDistributionError(
            "A solicitação de distribuição não pode ser incluída no SOAP."
        ) from error
    envelope = etree.Element(
        etree.QName(SOAP12_NAMESPACE, "Envelope"),
        nsmap={"soap12": SOAP12_NAMESPACE},
    )
    header = etree.SubElement(envelope, etree.QName(SOAP12_NAMESPACE, "Header"))
    message_header = etree.SubElement(
        header,
        etree.QName(WSDL_NAMESPACE, "nfeCabecMsg"),
    )
    etree.SubElement(
        message_header,
        etree.QName(WSDL_NAMESPACE, "versaoDados"),
    ).text = "1.01"
    etree.SubElement(message_header, etree.QName(WSDL_NAMESPACE, "cUF")).text = "91"
    body = etree.SubElement(envelope, etree.QName(SOAP12_NAMESPACE, "Body"))
    operation = etree.SubElement(
        body,
        etree.QName(WSDL_NAMESPACE, "nfeDistDFeInteresse"),
    )
    message = etree.SubElement(operation, etree.QName(WSDL_NAMESPACE, "nfeDadosMsg"))
    message.append(request_root)
    return etree.tostring(envelope, encoding="utf-8", xml_declaration=True)


def extract_distribution_response(soap_response: bytes) -> bytes:
    """Extract exactly one validated ``retDistDFeInt`` from a SOAP 1.2 response."""
    root = _parse_soap(soap_response)
    body = root.find(f"{{{SOAP12_NAMESPACE}}}Body")
    if body is None:
        raise SefazDistributionError("A resposta SOAP não contém Body.")
    if body.find(f"{{{SOAP12_NAMESPACE}}}Fault") is not None:
        raise SefazDistributionError("A SEFAZ retornou uma falha SOAP.")
    payloads = body.xpath(
        ".//*[local-name()='retDistDFeInt' and "
        "namespace-uri()='http://www.portalfiscal.inf.br/nfe']"
    )
    if len(payloads) == 1:
        distribution_response = etree.tostring(
            payloads[0],
            encoding="utf-8",
            xml_declaration=True,
        )
    elif not payloads:
        distribution_response = _extract_escaped_result(body)
    else:
        raise SefazDistributionError(
            "A resposta SOAP contém mais de um retorno fiscal."
        )
    try:
        validate_fiscal_xml(distribution_response, expected_root="retDistDFeInt")
    except FiscalSchemaError as error:
        raise SefazDistributionError(
            "O retorno da SEFAZ não atende ao schema da distribuição."
        ) from error
    return distribution_response


def _environment_code(environment: str) -> str:
    if environment == "production":
        return "1"
    if environment == "homologation":
        return "2"
    raise SefazDistributionError("Ambiente fiscal inválido para distribuição.")


def _normalise_nsu(value: str) -> str:
    if not value:
        return "0".zfill(15)
    if not value.isdecimal() or len(value) > 15:
        raise SefazDistributionError("O cursor NSU persistido é inválido.")
    return value.zfill(15)


def _parse_soap(payload: bytes) -> etree._Element:
    if not payload or len(payload) > settings.SEFAZ_MAX_RESPONSE_BYTES:
        raise SefazDistributionError("A resposta SOAP está vazia ou excede o limite.")
    if b"<!DOCTYPE" in payload.upper():
        raise SefazDistributionError("DOCTYPE não é permitido na resposta SOAP.")
    parser = etree.XMLParser(
        resolve_entities=False,
        no_network=True,
        load_dtd=False,
        huge_tree=False,
    )
    try:
        root = etree.fromstring(payload, parser=parser)
    except etree.XMLSyntaxError as error:
        raise SefazDistributionError("A resposta SOAP não é bem-formada.") from error
    if (
        etree.QName(root).namespace != SOAP12_NAMESPACE
        or etree.QName(root).localname != "Envelope"
    ):
        raise SefazDistributionError("A resposta não usa o envelope SOAP 1.2 esperado.")
    return root


def _extract_escaped_result(body: etree._Element) -> bytes:
    results = body.xpath(
        ".//*[local-name()='nfeDistDFeInteresseResult' and "
        "namespace-uri()='http://www.portalfiscal.inf.br/nfe/wsdl/NFeDistribuicaoDFe']"
    )
    if len(results) != 1 or not (results[0].text or "").strip():
        raise SefazDistributionError(
            "A resposta SOAP não contém retorno de distribuição."
        )
    return results[0].text.strip().encode("utf-8")


def _read_bounded_response(response: requests.Response) -> bytes:
    chunks: list[bytes] = []
    total = 0
    for chunk in response.iter_content(chunk_size=64 * 1024):
        if not chunk:
            continue
        total += len(chunk)
        if total > settings.SEFAZ_MAX_RESPONSE_BYTES:
            raise SefazTransportError("A resposta da SEFAZ excede o limite aceito.")
        chunks.append(chunk)
    return b"".join(chunks)


@contextmanager
def _temporary_client_certificate(
    pfx_payload: bytes,
    password: str,
) -> Iterator[tuple[str, str]]:
    try:
        private_key, certificate, additional_certificates = (
            pkcs12.load_key_and_certificates(pfx_payload, password.encode("utf-8"))
        )
    except (TypeError, ValueError) as error:
        raise SefazTransportError(
            "O certificado A1 não pôde ser convertido para TLS."
        ) from error
    if private_key is None or certificate is None:
        raise SefazTransportError("O certificado A1 não contém chave privada.")
    certificate_material = certificate.public_bytes(serialization.Encoding.PEM)
    for additional_certificate in additional_certificates or ():
        certificate_material += additional_certificate.public_bytes(
            serialization.Encoding.PEM
        )
    key_material = private_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    certificate_path = _write_private_temporary_file(certificate_material)
    key_path = _write_private_temporary_file(key_material)
    try:
        yield str(certificate_path), str(key_path)
    finally:
        for path in (certificate_path, key_path):
            try:
                path.unlink()
            except FileNotFoundError:
                pass
        certificate_material = b""
        key_material = b""


def _write_private_temporary_file(payload: bytes) -> Path:
    descriptor, temporary_name = tempfile.mkstemp(prefix="sefaz-mtls-", suffix=".pem")
    path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as temporary_file:
            os.fchmod(temporary_file.fileno(), 0o600)
            temporary_file.write(payload)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
    except Exception:
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        raise
    return path
