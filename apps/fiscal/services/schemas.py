"""Bounded, offline XML parsing for ATF invoice and event validation."""

from __future__ import annotations

from lxml import etree

NFE_NAMESPACE = "http://www.portalfiscal.inf.br/nfe"
MAX_FISCAL_XML_BYTES = 10 * 1024 * 1024


class FiscalSchemaError(ValueError):
    """A fiscal XML payload is malformed or outside its pinned XSD contract."""


def parse_fiscal_xml(payload: bytes) -> etree._Element:
    """Parse bounded XML without DTDs, entity resolution, or network fetches."""
    if not payload or len(payload) > MAX_FISCAL_XML_BYTES:
        raise FiscalSchemaError("O XML fiscal está vazio ou excede o limite aceito.")
    if b"<!DOCTYPE" in payload.upper():
        raise FiscalSchemaError("DOCTYPE não é permitido em XML fiscal.")
    parser = etree.XMLParser(
        resolve_entities=False,
        no_network=True,
        load_dtd=False,
        huge_tree=False,
    )
    try:
        root = etree.fromstring(payload, parser=parser)
    except etree.XMLSyntaxError as error:
        raise FiscalSchemaError("O XML fiscal não é bem-formado.") from error
    if etree.QName(root).namespace != NFE_NAMESPACE:
        raise FiscalSchemaError("O namespace do XML fiscal não é suportado.")
    return root
