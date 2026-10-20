"""Read the CNPJ bound to an ICP-Brasil enterprise certificate."""

import re

from cryptography import x509
from cryptography.x509.oid import NameOID, ObjectIdentifier

from apps.organizations.validators import normalize_tax_identifier

from .vault import CertificateValidationError


def certificate_cnpj(certificate: x509.Certificate) -> str:
    names: x509.SubjectAlternativeName | list[x509.GeneralName]
    try:
        names = certificate.extensions.get_extension_for_class(
            x509.SubjectAlternativeName
        ).value
    except x509.ExtensionNotFound:
        names = []
    values = set()
    for name in names:
        if not isinstance(name, x509.OtherName) or name.type_id != ObjectIdentifier(
            "2.16.76.1.3.3"
        ):
            continue
        encoded = name.value
        if len(encoded) == 16 and encoded[0] in (4, 12, 19, 22) and encoded[1] == 14:
            value = encoded[2:].decode("ascii", errors="strict")
            if re.fullmatch(r"[0-9A-Z]{12}[0-9]{2}", value):
                values.add(value)
    if not values:
        for attribute in certificate.subject.get_attributes_for_oid(
            NameOID.COMMON_NAME
        ):
            match = re.search(r":([0-9A-Z]{12}[0-9]{2})$", str(attribute.value))
            if match:
                values.add(normalize_tax_identifier(match[1]))
    if len(values) != 1:
        raise CertificateValidationError("O certificado não identifica um único CNPJ.")
    return values.pop()
