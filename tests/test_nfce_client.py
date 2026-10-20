from datetime import date

from apps.fiscal.atf.types import Period
from tests.test_atf_authentication import Response, Session


def test_a1_landing_with_message_form_is_authenticated_without_login_label(tmp_path):
    from apps.fiscal.atf.client import AtfPbClient

    page = (
        b'<body>Bom dia, Conta de exemplo <a>Sair</a><form name="formMensagens">'
        b'<input name="hidAcao"></form></body>'
    )
    client = AtfPbClient(
        Session([Response(b'<form name="FormLogin"></form>'), Response(page)]),
        "00000000000191",
        tmp_path,
    )
    assert len(client.authenticate().account_key) == 64


def test_a1_identity_stays_stable_when_portal_landing_changes(tmp_path):
    from apps.fiscal.atf.client import AtfPbClient

    identities = []
    for landing in [
        b"<body>Login: example-account <a>Sair</a></body>",
        b'<body><a>Sair</a><form name="formMensagens"></form></body>',
    ]:
        client = AtfPbClient(
            Session([Response(b'<form name="FormLogin"></form>'), Response(landing)]),
            "00000000000191",
            tmp_path,
        )
        identities.append(client.authenticate().account_key)
    assert identities[0] == identities[1]


def test_resumed_legacy_a1_request_keeps_its_recorded_account_namespace(tmp_path):
    from apps.fiscal.atf.client import AtfPbClient

    landing = b'<body><a>Sair</a><form name="formMensagens"></form></body>'
    client = AtfPbClient(
        Session([Response(b'<form name="FormLogin"></form>'), Response(landing)]),
        "00000000000191",
        tmp_path,
        account_key_hint="a" * 64,
    )
    assert client.authenticate().account_key == "a" * 64


def test_nfce_issuer_and_query_use_observed_endpoint_and_txt_option(tmp_path):
    from apps.fiscal.atf.client import AtfPbClient

    issuer = b"""<script>
    parent.frmConsultar.hidSqHumanoInstcmpEmit.value="42";
    parent.frmConsultar.hidCNPJcmpEmit.value="00000000000191";
    </script>"""
    session = Session(
        [
            Response(
                b'<form name="frmConsultar"><input name="edtNrNota" value=""></form>'
            ),
            Response(
                b'<form name="iform"><input name="id" '
                b'value="FISf_ConsultaGenericaEmitenteNFCe_cmpEmit"></form>'
            ),
            Response(issuer),
            Response("O resultado será enviado para sua caixa de mensagens".encode()),
        ]
    )
    client = AtfPbClient(session, "00000000000191", tmp_path)
    identity = client.lookup_issuer("00000000000191", document_model="65")
    result = client.submit_query(
        identity,
        Period(date(2024, 10, 10), date(2024, 10, 10)),
        "txt",
        document_model="65",
    )
    assert result.accepted
    assert session.calls[0][1].endswith(
        "/atf/fis/FISf_ConsultaGenericaEmitenteNFCe.do?idSERVirtual=S"
    )
    assert "id=FISf_ConsultaGenericaEmitenteNFCe_cmpEmit" in session.calls[1][1]
    assert session.calls[3][1].endswith("/atf/fis/FISf_ConsultaGenericaEmitenteNFCe.do")
    data = session.calls[3][2]["data"]
    assert data["edtDtInicial"] == data["edtDtFinal"] == "10/10/2024"
    assert data["cmbTpExibicao"] == "2"
    assert data["cmbTpDoccmpEmit"] == "2"
