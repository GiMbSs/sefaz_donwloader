"""Local, pinned XSD validation for the NF-e distribution contracts."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from django.conf import settings
from lxml import etree


NFE_NAMESPACE = "http://www.portalfiscal.inf.br/nfe"
MAX_FISCAL_XML_BYTES = 10 * 1024 * 1024

_SCHEMA_FILES = {
    "distDFeInt": "distDFeInt_v1.01.xsd",
    "retDistDFeInt": "retDistDFeInt_v1.01.xsd",
    "resNFe": "resNFe_v1.01.xsd",
    "resEvento": "resEvento_v1.01.xsd",
}
_SCHEMA_ROOTS = {filename: root for root, filename in _SCHEMA_FILES.items()}


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


def validate_fiscal_xml(payload: bytes, *, expected_root: str) -> etree._Element:
    """Validate a pinned NF-e distribution payload and return its parsed root."""
    root = parse_fiscal_xml(payload)
    if etree.QName(root).localname != expected_root:
        raise FiscalSchemaError("O XML fiscal tem uma raiz inesperada.")
    try:
        _load_schema(expected_root).assertValid(root)
    except etree.DocumentInvalid as error:
        raise FiscalSchemaError(
            f"O XML fiscal não atende ao schema {expected_root}."
        ) from error
    return root


def known_distributed_schema(schema_name: str) -> str | None:
    """Return the expected root for a locally supported ``docZip`` schema."""
    return _SCHEMA_ROOTS.get(Path(schema_name).name)


@lru_cache(maxsize=len(_SCHEMA_FILES))
def _load_schema(root_name: str) -> etree.XMLSchema:
    try:
        filename = _SCHEMA_FILES[root_name]
    except KeyError as error:
        raise FiscalSchemaError("Não há schema local para este tipo de XML.") from error
    schema_path = settings.FISCAL_SCHEMA_ROOT / "distribuicao" / filename
    if not schema_path.is_file():
        raise FiscalSchemaError("O schema fiscal local obrigatório não foi encontrado.")
    parser = etree.XMLParser(
        resolve_entities=False,
        no_network=True,
        load_dtd=False,
        huge_tree=False,
    )
    try:
        return etree.XMLSchema(etree.parse(str(schema_path), parser=parser))
    except (OSError, etree.XMLSchemaParseError, etree.XMLSyntaxError) as error:
        raise FiscalSchemaError(
            "O schema fiscal local não pôde ser carregado."
        ) from error
