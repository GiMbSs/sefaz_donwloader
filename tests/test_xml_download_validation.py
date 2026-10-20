import hashlib
from datetime import date

import pytest

from apps.fiscal.atf.errors import AtfError
from apps.fiscal.atf.types import Period
from tests.test_download_archives import EVENT, INVOICE, KEY, archive_file

NAMESPACE = b'xmlns="http://www.portalfiscal.inf.br/nfe"'


def invoice(model="55", namespace="standard"):
    key = KEY[:20] + model + KEY[22:]
    body = INVOICE.replace(KEY.encode(), key.encode()).replace(
        b"<mod>55</mod>", f"<mod>{model}</mod>".encode()
    )
    if namespace == "wrapper":
        body = body.replace(b"<nfeProc " + NAMESPACE + b">", b"<nfeProc>")
        body = body.replace(b"<NFe>", b"<NFe " + NAMESPACE + b">")
    elif namespace == "none":
        body = body.replace(b" " + NAMESPACE, b"")
    return body


@pytest.mark.parametrize("model", ["55", "65"])
@pytest.mark.parametrize("namespace", ["standard", "wrapper", "none"])
def test_xml_exports_are_checked_without_rewriting_original_bytes(
    tmp_path, download_company, model, namespace
):
    from apps.fiscal.services.artifacts import validate_archive

    body = invoice(model, namespace)
    validated = validate_archive(
        archive_file(tmp_path, [("note.xml", body)]),
        company_id=download_company.pk,
        period=Period(date(2024, 10, 10), date(2024, 10, 10)),
        format="xml",
        document_model=model,
    )
    member = validated.members[0]
    assert member.metadata["number"] == "1"
    assert member.metadata["model"] == model
    assert member.metadata["validation_status"] == "pending_schema"
    assert member.sha256 == hashlib.sha256(body).hexdigest()
    assert ("nonstandard_xml_namespace" in validated.warnings) == (
        namespace != "standard"
    )


@pytest.mark.parametrize("model", ["55", "65"])
@pytest.mark.parametrize("namespace", ["standard", "wrapper", "none"])
@pytest.mark.parametrize(
    ("change", "expected_code"),
    [
        ("issuer", "atf_xml_issuer_mismatch"),
        ("key_issuer", "atf_xml_key_issuer_mismatch"),
        ("model", "atf_xml_model_mismatch"),
        ("key_model", "atf_xml_key_model_mismatch"),
        ("number", "atf_invoice_number_mismatch"),
        ("date", "atf_xml_date_invalid"),
        ("outside_period", "atf_invoice_outside_period"),
        ("id_prefix", "atf_xml_key_invalid"),
        ("protocol", "atf_invoice_key_mismatch"),
    ],
)
def test_xml_identity_model_number_date_and_protocol_are_enforced(
    tmp_path, download_company, model, namespace, change, expected_code
):
    from apps.fiscal.services.artifacts import validate_archive

    body = invoice(model, namespace)
    key = KEY[:20] + model + KEY[22:]
    if change == "issuer":
        body = body.replace(b"<CNPJ>00000000000191", b"<CNPJ>11222333000181")
    elif change == "key_issuer":
        body = body.replace(
            key.encode(), (key[:6] + "11222333000181" + key[20:]).encode()
        )
    elif change == "model":
        body = body.replace(f"<mod>{model}</mod>".encode(), b"<mod>57</mod>")
    elif change == "key_model":
        body = body.replace(key.encode(), (key[:20] + "57" + key[22:]).encode())
    elif change == "number":
        body = body.replace(b"<nNF>1</nNF>", b"<nNF>2</nNF>")
    elif change == "date":
        body = body.replace(b"T12:00:00", b"T99:99:99")
    elif change == "outside_period":
        body = body.replace(b"2024-10-10T", b"2024-10-11T")
    elif change == "id_prefix":
        body = body.replace(b'Id="NFe', b'Id="')
    elif change == "protocol":
        body = body.replace(
            b"</nfeProc>",
            b"<protNFe><infProt><chNFe>"
            + ("0" * 44).encode()
            + b"</chNFe></infProt></protNFe></nfeProc>",
        )
    with pytest.raises(AtfError) as error:
        validate_archive(
            archive_file(tmp_path, [("note.xml", body)]),
            company_id=download_company.pk,
            period=Period(date(2024, 10, 10), date(2024, 10, 10)),
            format="xml",
            document_model=model,
        )
    assert str(error.value) == expected_code


@pytest.mark.parametrize("model", ["55", "65"])
@pytest.mark.parametrize("namespace", ["standard", "wrapper", "none"])
def test_xml_event_export_checks_issuer_from_key_not_event_author(
    tmp_path, download_company, model, namespace
):
    from apps.fiscal.services.artifacts import validate_archive

    key = KEY[:20] + model + KEY[22:]
    body = EVENT.replace(KEY.encode(), key.encode())
    if namespace == "wrapper":
        body = body.replace(
            b"<procEventoNFe " + NAMESPACE + b">", b"<procEventoNFe>"
        ).replace(b"<evento>", b"<evento " + NAMESPACE + b">")
    elif namespace == "none":
        body = body.replace(b" " + NAMESPACE, b"")
    validated = validate_archive(
        archive_file(tmp_path, [("event.xml", body)]),
        company_id=download_company.pk,
        period=Period(date(2024, 10, 10), date(2024, 10, 10)),
        format="xml",
        document_model=model,
    )
    assert validated.members[0].kind == "event"
    assert validated.members[0].metadata["access_key"] == key


@pytest.mark.parametrize("model", ["55", "65"])
@pytest.mark.parametrize("variant", ["bare", "legacy_date", "midnight"])
def test_xml_supported_wrappers_and_dates_preserve_declared_emission_day(
    tmp_path, download_company, model, variant
):
    from apps.fiscal.services.artifacts import validate_archive

    body = invoice(model)
    if variant == "bare":
        body = body.replace(
            b"<nfeProc " + NAMESPACE + b"><NFe>", b"<NFe " + NAMESPACE + b">"
        )
        body = body.replace(b"</nfeProc>", b"")
    elif variant == "legacy_date":
        body = body.replace(
            b"<dhEmi>2024-10-10T12:00:00-03:00</dhEmi>",
            b"<dEmi>2024-10-10</dEmi>",
        )
    else:
        body = body.replace(b"T12:00:00-03:00", b"T23:45:00-03:00")
    result = validate_archive(
        archive_file(tmp_path, [("note.xml", body)]),
        company_id=download_company.pk,
        period=Period(date(2024, 10, 10), date(2024, 10, 10)),
        format="xml",
        document_model=model,
    )
    assert result.members[0].metadata["issued_on"] == "2024-10-10"


@pytest.mark.parametrize("model", ["55", "65"])
def test_xml_with_foreign_namespace_is_not_accepted_as_unqualified_export(
    tmp_path, download_company, model
):
    from apps.fiscal.services.artifacts import validate_archive

    body = invoice(model).replace(NAMESPACE, b'xmlns="urn:untrusted-fiscal-format"')
    with pytest.raises(AtfError):
        validate_archive(
            archive_file(tmp_path, [("note.xml", body)]),
            company_id=download_company.pk,
            period=Period(date(2024, 10, 10), date(2024, 10, 10)),
            format="xml",
            document_model=model,
        )
