import pytest


def test_issuer_parser_only_reads_known_literal_fields():
    from apps.fiscal.atf.forms import parse_issuer

    source = b"""<script>
      parent.frmConsultar.hidSqHumanoInstcmpEmit.value = "42";
      parent.frmConsultar.hidCNPJcmpEmit.value = "00.000.000/0001-91";
      parent.frmConsultar.hidTpNaturezacmpEmit.value = "I";
    </script>"""
    result = parse_issuer(source, "00000000000191")
    assert result.remote_id == "42"
    assert result.cnpj == "00000000000191"


def test_issuer_parser_rejects_expressions_and_other_cnpj():
    from apps.fiscal.atf.errors import AtfIdentityMismatch, AtfPortalChanged
    from apps.fiscal.atf.forms import parse_issuer

    with pytest.raises(AtfPortalChanged):
        parse_issuer(
            b"<script>parent.frmConsultar.hidSqHumanoInstcmpEmit.value "
            b"= evil();</script>",
            "00000000000191",
        )
    with pytest.raises(AtfIdentityMismatch):
        parse_issuer(
            b"""<script>
            parent.frmConsultar.hidSqHumanoInstcmpEmit.value = "42";
            parent.frmConsultar.hidCNPJcmpEmit.value = "11111111000111";
        </script>""",
            "00000000000191",
        )
