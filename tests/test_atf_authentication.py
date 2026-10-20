import pytest
import requests


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        (
            'attachment; filename="Consulta_01-10-2026_20-10-2026.zip"',
            "Consulta_01-10-2026_20-10-2026.zip",
        ),
        (
            "attachment; filename=Consulta_01-10-2026_20-10-2026.zip",
            "Consulta_01-10-2026_20-10-2026.zip",
        ),
        (
            "attachment; filename=ascii.zip; "
            "filename*=UTF-8''Consulta%20NF-e%20outubro.zip",
            "Consulta NF-e outubro.zip",
        ),
        (
            "attachment; filename*=UTF-8''Consulta%20emiss%C3%A3o.zip",
            "Consulta emissão.zip",
        ),
        ('attachment; filename="../../escape.zip"', "fallback.zip"),
        ('attachment; filename="C:\\escape.zip"', "fallback.zip"),
        ('attachment; filename="CON.zip"', "fallback.zip"),
        ("", "fallback.zip"),
    ],
)
def test_download_retains_safe_original_filename(tmp_path, header, expected):
    from apps.fiscal.atf.client import AtfPbClient
    from apps.fiscal.atf.types import AttachmentRef

    response = Response(b"PK\x03\x04synthetic zip stream")
    response.headers.update(
        {"Content-Type": "application/zip", "Content-Disposition": header}
    )
    client = AtfPbClient(Session([response]), "00000000000191", tmp_path)
    client.current_message = "10"
    download = client.download_attachment(AttachmentRef("10", 0, "fallback.zip"))
    assert download.filename == expected
    assert download.staging_path.read_bytes() == response.content


class Response:
    def __init__(self, body=b"", status=200, location=None):
        self.status_code = status
        self.content = body
        self.headers = {"Content-Type": "text/html"}
        if location:
            self.headers["Location"] = location
        self.url = ""

    def iter_content(self, chunk_size=65536):
        yield self.content

    def close(self):
        pass


class Session:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        result = next(self.responses)
        if isinstance(result, Exception):
            raise result
        result.url = url
        return result

    def close(self):
        pass


def test_authentication_preserves_form_and_hashes_remote_identity(tmp_path):
    from apps.fiscal.atf.client import AtfPbClient

    session = Session(
        [
            Response(
                b'<form name="FormLogin"><input type="hidden" '
                b'name="tpl" value="full"></form>'
            ),
            Response(
                status=302, location="/atf/seg/SEGf_LoginCertificadoSERvirtual.do"
            ),
            Response(b'<body>Login: synthetic-user <a href="logout">Sair</a></body>'),
        ]
    )
    client = AtfPbClient(session, "00000000000191", tmp_path)
    identity = client.authenticate()
    assert len(identity.account_key) == 64
    assert "synthetic-user" not in identity.account_key
    assert session.calls[1][2]["data"] == {
        "tpl": "full",
        "hidAcao": "logarCertificadoDigital",
    }


def test_redirect_cannot_forward_credentials_to_external_host(tmp_path):
    from apps.fiscal.atf.client import AtfPbClient
    from apps.fiscal.atf.errors import AtfPermissionError

    session = Session([Response(status=302, location="https://attacker.test/")])
    client = AtfPbClient(session, "00000000000191", tmp_path)
    with pytest.raises(AtfPermissionError):
        client.authenticate()
    assert len(session.calls) == 1


def test_login_page_with_http_200_is_not_authenticated(tmp_path):
    from apps.fiscal.atf.client import AtfPbClient
    from apps.fiscal.atf.errors import AtfAuthenticationError

    login = b'<form name="FormLogin"><input type="password" name="senha"></form>'
    client = AtfPbClient(
        Session([Response(login), Response(login)]), "00000000000191", tmp_path
    )
    with pytest.raises(AtfAuthenticationError):
        client.authenticate()


def test_query_timeout_is_uncertain_and_is_not_retried(tmp_path):
    from datetime import date

    from apps.fiscal.atf.client import AtfPbClient
    from apps.fiscal.atf.errors import AtfSubmissionUncertain
    from apps.fiscal.atf.types import IssuerIdentity, Period

    session = Session([requests.Timeout("secret body must not be propagated")])
    client = AtfPbClient(session, "00000000000191", tmp_path)
    client.query_fields = {"hidAcao": ""}
    issuer = IssuerIdentity("00000000000191", "42", {"hidSqHumanoInstcmpEmit": "42"})
    with pytest.raises(AtfSubmissionUncertain) as error:
        client.submit_query(issuer, Period(date(2024, 1, 1), date(2024, 1, 2)), "xml")
    assert len(session.calls) == 1
    assert "secret" not in str(error.value)


def test_client_keeps_lease_alive_while_reading_responses(tmp_path):
    from apps.fiscal.atf.client import AtfPbClient

    renewed = []
    session = Session(
        [
            Response(b'<form name="FormLogin"></form>'),
            Response(b"<body>Login: synthetic-user <a>Sair</a></body>"),
        ]
    )
    client = AtfPbClient(session, "00000000000191", tmp_path)
    client.heartbeat = lambda: renewed.append(True)
    client.authenticate()
    assert renewed


def test_rate_limit_preserves_longer_retry_after(tmp_path):
    from apps.fiscal.atf.client import AtfPbClient
    from apps.fiscal.atf.errors import AtfTransientError

    response = Response(status=429)
    response.headers["Retry-After"] = "1200"
    client = AtfPbClient(Session([response]), "00000000000191", tmp_path)
    with pytest.raises(AtfTransientError) as error:
        client.authenticate()
    assert error.value.retry_after_seconds == 1200


def test_slow_attachment_stream_is_transient_and_removes_partial_file(tmp_path):
    from apps.fiscal.atf.client import AtfPbClient
    from apps.fiscal.atf.errors import AtfTransientError
    from apps.fiscal.atf.types import AttachmentRef

    class Interrupted(Response):
        def iter_content(self, chunk_size=65536):
            yield b"PK\x03\x04partial"
            raise requests.ConnectionError("private response content")

    client = AtfPbClient(Session([Interrupted()]), "00000000000191", tmp_path)
    client.current_message = "10"
    with pytest.raises(AtfTransientError):
        client.download_attachment(AttachmentRef("10", 0))
    assert list(tmp_path.iterdir()) == []
