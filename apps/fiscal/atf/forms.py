import re
from typing import Any

from lxml import etree, html

from apps.organizations.validators import normalize_tax_identifier

from .errors import AtfIdentityMismatch, AtfPortalChanged
from .types import IssuerIdentity


def portal_document(content: bytes) -> Any:
    try:
        declared = re.search(rb'charset\s*=\s*["\']?([a-zA-Z0-9_-]+)', content[:4096])
        encoding = declared[1].decode("ascii") if declared else "utf-8"
        if not declared:
            try:
                content.decode("utf-8")
            except UnicodeDecodeError:
                encoding = "windows-1252"
        return html.fromstring(content, parser=html.HTMLParser(encoding=encoding))
    except (etree.ParserError, LookupError, ValueError) as error:
        raise AtfPortalChanged() from error


def visible_text(tree: Any) -> str:
    return " ".join(
        " ".join(
            tree.xpath("//body//text()[not(ancestor::script) and not(ancestor::style)]")
            or tree.xpath("//text()[not(ancestor::script) and not(ancestor::style)]")
        ).split()
    )


def form_fields(content: bytes, name: str) -> dict[str, str]:
    forms = portal_document(content).xpath("//form[@name=$name]", name=name)
    if len(forms) != 1:
        raise AtfPortalChanged()
    result = {}
    for element in forms[0].xpath(
        ".//input[@name] | .//select[@name] | .//textarea[@name]"
    ):
        if element.get("disabled") is not None or element.get("type") in {
            "submit",
            "button",
            "file",
        }:
            continue
        if (
            element.get("type") in {"checkbox", "radio"}
            and element.get("checked") is None
        ):
            continue
        if element.tag == "select":
            options = (
                element.xpath("./option[@selected]") or element.xpath("./option")[:1]
            )
            value = options[0].get("value", options[0].text or "") if options else ""
        elif element.tag == "textarea":
            value = element.text or ""
        else:
            value = element.get("value", "")
        result[element.get("name")] = value
    return result


def parse_issuer(content: bytes, expected_cnpj: str) -> IssuerIdentity:
    tree = portal_document(content)
    source = "\n".join(tree.xpath("//script[not(@src)]/text()"))
    fields = {}
    allowed = {
        "hidTsAtualizacaocmpEmit",
        "hidNrDocumentocmpEmit",
        "hidSqHumanoInstcmpEmit",
        "hidCNPJcmpEmit",
        "hidNrInscrEstadualcmpEmit",
        "hidCdSIAFcmpEmit",
        "hidCnpjCpfcmpEmit",
        "hidCPFcmpEmit",
        "hidTpNaturezacmpEmit",
        "hidNrATFcmpEmit",
    }
    # Accept literal scalar assignments only; never evaluate JavaScript.
    pattern = (
        r"""parent\.(?:document\.)?frmConsultar\.(\w+)\.value\s*=\s*"""
        r"""(["'])([^"'\\\r\n]*)\2\s*;?"""
    )
    for match in re.finditer(pattern, source):
        if match[1] in allowed:
            fields[match[1]] = match[3]
    remote_id = fields.get("hidSqHumanoInstcmpEmit", "")
    cnpj = normalize_tax_identifier(fields.get("hidCNPJcmpEmit", ""))
    if not remote_id.isdigit() or not cnpj:
        raise AtfPortalChanged()
    if cnpj != normalize_tax_identifier(expected_cnpj):
        raise AtfIdentityMismatch()
    fields["cmbTpDoccmpEmit"] = "2"
    return IssuerIdentity(cnpj, remote_id, fields)
