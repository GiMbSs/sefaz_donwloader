"""NFC-e submission routing and the official button in a real offline browser."""

import os
from contextlib import contextmanager
from datetime import date, time

import pytest

from apps.fiscal.atf.client import AtfPbClient
from apps.fiscal.atf.errors import (
    AtfCaptchaRequired,
    AtfIdentityMismatch,
    AtfPermissionError,
    AtfSubmissionUncertain,
    AtfTransientError,
)
from apps.fiscal.atf.types import (
    IssuerIdentity,
    Period,
    RemoteIdentity,
    SubmissionReceipt,
)
from tests.test_atf_authentication import Response, Session

CNPJ = "00000000000191"
PERIOD = Period(date(2026, 10, 21), date(2026, 10, 21))
QUERY = "/atf/fis/FISf_ConsultaGenericaEmitenteNFCe.do"
ACCEPTED = (
    '<meta charset="utf-8"><body>'
    "O resultado será enviado para sua caixa de mensagens do ATF</body>"
).encode("cp1252")


class PreparedQuery:
    def __init__(self):
        self.lookups = []
        self.submissions = []

    def lookup_issuer(self, cnpj):
        self.lookups.append(cnpj)
        return IssuerIdentity(cnpj, "42", {})

    def submit_query(self, issuer, period, format):
        self.submissions.append((issuer.cnpj, period, format))
        return SubmissionReceipt(True)

    def prepare_query(self, issuer, period, format):
        pass


@pytest.mark.parametrize("format", ["xml", "txt"])
def test_only_nfce_uses_prepared_browser_without_http_query(tmp_path, format):
    browser = PreparedQuery()
    session = Session([])
    client = AtfPbClient(session, CNPJ, tmp_path, nfce_query_factory=lambda: browser)
    issuer = client.lookup_issuer(CNPJ, document_model="65")
    assert client.submit_query(issuer, PERIOD, format, document_model="65").accepted
    assert browser.lookups == [CNPJ]
    assert browser.submissions == [(CNPJ, PERIOD, format)]
    assert session.calls == []


def test_nfe_keeps_http_submission_and_never_opens_browser(tmp_path):
    def unexpected_browser():
        pytest.fail("NF-e started the NFC-e browser")

    source = b'<form name="frmConsultar"><input name="hidAcao" value=""></form>'
    issuer_source = (
        '<script>parent.frmConsultar.hidSqHumanoInstcmpEmit.value="42";'
        f'parent.frmConsultar.hidCNPJcmpEmit.value="{CNPJ}";</script>'
    ).encode()
    session = Session(
        [
            Response(source),
            Response(b'<form name="iform"></form>'),
            Response(issuer_source),
            Response(ACCEPTED),
        ]
    )
    client = AtfPbClient(session, CNPJ, tmp_path, nfce_query_factory=unexpected_browser)
    issuer = client.lookup_issuer(CNPJ, document_model="55")
    assert client.submit_query(issuer, PERIOD, "xml", document_model="55").accepted
    assert session.calls[-1][0] == "POST"
    assert session.calls[-1][1].endswith("FISf_ConsultarNFeXml2.do")


@pytest.mark.parametrize("trigger", ["manual", "scheduled"])
@pytest.mark.parametrize("format", ["xml", "txt"])
@pytest.mark.parametrize("prepare_failure", [False, True])
def test_nfce_browser_prepares_before_intent_and_clicks_after_barriers(
    download_company, download_actor, tmp_path, trigger, format, prepare_failure
):
    from apps.fiscal.models import DownloadPolicy, RemoteSubmissionBarrier
    from apps.fiscal.services.downloads import advance_part, request_download

    DownloadPolicy.objects.create(
        company=download_company,
        mode="automatic",
        is_active=True,
        scheduled_time=time(2),
    )
    request = request_download(
        company_id=download_company.pk,
        period=PERIOD,
        formats=(format,),
        document_model="65",
        trigger=trigger,
        dispatch=False,
        actor_id=download_actor.pk if trigger == "manual" else None,
    )
    part = request.parts.get()

    class GuardedQuery(PreparedQuery):
        def lookup_issuer(self, cnpj):
            part.refresh_from_db()
            assert part.submitted_at is None
            assert not RemoteSubmissionBarrier.objects.filter(part=part).exists()
            if prepare_failure:
                raise AtfPermissionError("atf_nfce_browser_unavailable")
            return super().lookup_issuer(cnpj)

        def submit_query(self, *args):
            part.refresh_from_db()
            assert part.status == "submitting"
            assert RemoteSubmissionBarrier.objects.filter(part=part).count() == 2
            return super().submit_query(*args)

    browser = GuardedQuery()

    @contextmanager
    def factory(company_id):
        client = AtfPbClient(
            Session([Response(b'<form name="frmMensagens"></form>')]),
            CNPJ,
            tmp_path,
            nfce_query_factory=lambda: browser,
        )
        client.identity = RemoteIdentity("a" * 64)
        yield client

    result = advance_part(part.pk, client_factory=factory, dispatch=False)
    if prepare_failure:
        assert result.status == "failed"
        part.refresh_from_db()
        assert part.error_code == "atf_nfce_browser_unavailable"
        assert part.submitted_at is None
        assert not RemoteSubmissionBarrier.objects.filter(part=part).exists()
        assert not browser.submissions
        return
    assert result.status == "waiting"
    part.refresh_from_db()
    assert part.attempts.get().submission_certainty == "accepted"
    assert len(browser.submissions) == 1
    assert part.next_poll_at >= part.submitted_at


def test_production_client_registers_and_closes_only_nfce_browser(
    binding, settings, monkeypatch
):
    from apps.fiscal.atf.client import open_atf_client

    settings.ATF_PB_ENABLED = True
    certificate, _ = binding
    events = []

    @contextmanager
    def factory(certificate_id, *, heartbeat):
        assert certificate_id == certificate.pk
        events.append("opened")
        try:
            yield PreparedQuery()
        finally:
            events.append("closed")

    def authenticate(client):
        client.identity = RemoteIdentity("a" * 64)
        return client.identity

    monkeypatch.setattr(AtfPbClient, "authenticate", authenticate)
    monkeypatch.setattr("apps.fiscal.atf.nfce_browser.open_nfce_query", factory)
    with open_atf_client(certificate.company_id) as client:
        assert events == []
        issuer = client.lookup_issuer(CNPJ, document_model="65")
        assert client.submit_query(issuer, PERIOD, "xml", document_model="65").accepted
        assert events == ["opened"]
    assert events == ["opened", "closed"]


@pytest.mark.parametrize("trigger", ["manual", "scheduled"])
def test_nfce_date_form_failure_happens_before_intent(
    download_company, download_actor, tmp_path, trigger
):
    from apps.fiscal.models import DownloadPolicy, RemoteSubmissionBarrier
    from apps.fiscal.services.downloads import advance_part, request_download

    DownloadPolicy.objects.create(
        company=download_company,
        mode="automatic",
        is_active=True,
        scheduled_time=time(2),
    )
    request = request_download(
        company_id=download_company.pk,
        period=PERIOD,
        formats=("xml",),
        document_model="65",
        trigger=trigger,
        dispatch=False,
        actor_id=download_actor.pk if trigger == "manual" else None,
    )
    part = request.parts.get()

    class BrokenForm(PreparedQuery):
        def prepare_query(self, issuer, period, format):
            part.refresh_from_db()
            assert part.submitted_at is None
            raise AtfTransientError("atf_nfce_browser_timeout")

    browser = BrokenForm()

    @contextmanager
    def factory(company_id):
        client = AtfPbClient(
            Session([Response(b'<form name="frmMensagens"></form>')]),
            CNPJ,
            tmp_path,
            nfce_query_factory=lambda: browser,
        )
        client.identity = RemoteIdentity("a" * 64)
        yield client

    assert (
        advance_part(part.pk, client_factory=factory, dispatch=False).status == "queued"
    )
    part.refresh_from_db()
    assert part.submitted_at is None
    assert part.retry_count == 1
    assert not RemoteSubmissionBarrier.objects.filter(part=part).exists()
    assert not browser.submissions


def test_browser_startup_failure_is_sanitized_and_stops_driver(binding, monkeypatch):
    from types import SimpleNamespace

    from playwright.sync_api import Error

    from apps.fiscal.atf.nfce_browser import open_nfce_query

    certificate, _ = binding
    events = []

    def launch(**kwargs):
        raise Error("private synthetic transport details")

    driver = SimpleNamespace(
        chromium=SimpleNamespace(launch=launch), stop=lambda: events.append("stopped")
    )
    monkeypatch.setattr(
        "apps.fiscal.atf.nfce_browser.sync_playwright",
        lambda: SimpleNamespace(start=lambda: driver),
    )
    with pytest.raises(
        AtfPermissionError, match="atf_nfce_browser_unavailable"
    ) as error:
        with open_nfce_query(certificate.pk):
            pytest.fail("Unavailable browser was accepted")
    assert "private synthetic" not in str(error.value)
    assert events == ["stopped"]


@pytest.fixture
def offline_browser(binding, settings):
    if os.environ.get("RUN_BROWSER_TESTS") != "1":
        pytest.skip("Set RUN_BROWSER_TESTS=1 with Playwright Chromium installed")
    from urllib.parse import parse_qs, urlsplit

    from apps.fiscal.atf.nfce_browser import open_nfce_query

    settings.ATF_NFCE_BROWSER_TIMEOUT_SECONDS = 1.5
    certificate, _ = binding
    state = {
        "posts": [],
        "response": ACCEPTED,
        "status": 200,
        "abort": False,
        "masked_issuer": False,
    }
    with open_nfce_query(
        certificate.pk, heartbeat=lambda: type(certificate).objects.count()
    ) as query:

        def portal(route):
            request = route.request
            path = urlsplit(request.url).path
            if path == QUERY and request.method == "POST":
                state["posts"].append(parse_qs(request.post_data))
                if state["abort"]:
                    route.abort("timedout")
                else:
                    route.fulfill(status=state["status"], body=state["response"])
                return
            if path == QUERY:
                body = f'''<form name="frmConsultar" method="post" action="{QUERY}">
                  <input name="hidAcao" value="consultar" type="hidden">
                  <input name="hidCNPJcmpEmit" type="hidden">
                  <input name="hidSqHumanoInstcmpEmit" type="hidden">
                  <input name="edtDtInicial"><input name="edtDtFinal">
                  <select name="cmbTpDoccmpEmit"><option value="1">IE</option>
                    <option value="2">CNPJ</option></select>
                  <iframe name="cmpEmit" src="/atf/componentes/issuer"></iframe>
                  <select name="cmbTpExibicao"><option value="2">TXT</option>
                    <option value="3">XML</option></select>
                  <input name="g-recaptcha-response" type="hidden">
                  <button name="btnConsultar" onclick="event.preventDefault();
                    setTimeout(() => {{
                      document.querySelector('[name=g-recaptcha-response]').value=
                        'synthetic-official-button-result';
                      document.frmConsultar.submit();
                    }}, 30);">Consultar</button></form>'''
            elif path == "/atf/componentes/issuer":
                assignment = "document.querySelector('input').value"
                if state["masked_issuer"]:
                    assignment += (
                        ".replace(/(\\d{2})(\\d{3})(\\d{3})(\\d{4})(\\d{2})/,"
                        " '$1.$2.$3/$4-$5')"
                    )
                body = """<input name="hidNrDocumentocmpEmit">
                  <button name="btnPesquisar" onclick="
                    parent.document.frmConsultar.hidCNPJcmpEmit.value=ASSIGNMENT;
                    parent.document.frmConsultar.hidSqHumanoInstcmpEmit.value='42';
                  ">Pesquisar</button>""".replace("ASSIGNMENT", assignment)
            elif path.endswith("SEGf_LoginSERVirtual.jsp"):
                body = '<a href="/atf/seg/landing">Acesso via Certificado Digital</a>'
            else:
                body = '<form name="formMensagens"></form><a>Sair</a>'
            route.fulfill(body=body, content_type="text/html; charset=utf-8")

        query._call(lambda: query._query.page.route("**/*", portal))
        yield query, state
    assert query.closed


@pytest.mark.parametrize("format,remote_format", [("xml", "3"), ("txt", "2")])
def test_real_browser_runs_official_button_once(offline_browser, format, remote_format):
    query, state = offline_browser
    issuer = query.lookup_issuer(CNPJ)
    assert state["posts"] == []
    assert query.submit_query(issuer, PERIOD, format).accepted
    assert len(state["posts"]) == 1
    submitted = state["posts"][0]
    assert submitted["edtDtInicial"] == ["21/10/2026"]
    assert submitted["edtDtFinal"] == ["21/10/2026"]
    assert submitted["cmbTpExibicao"] == [remote_format]
    assert submitted["hidCNPJcmpEmit"] == [CNPJ]
    assert submitted["g-recaptcha-response"] == ["synthetic-official-button-result"]


def test_real_browser_reports_explicit_captcha_rejection(offline_browser):
    query, state = offline_browser
    state["response"] = b"""<script>var cod='3291';
    window.location='../seg/SEGf_EmitirMensagemTelaCheia.jsp?codigo='+cod;</script>"""
    issuer = query.lookup_issuer(CNPJ)
    with pytest.raises(AtfCaptchaRequired):
        try:
            query.submit_query(issuer, PERIOD, "txt")
        except AtfSubmissionUncertain as error:
            pytest.fail(f"Unexpected uncertain synthetic response: {error.__context__}")
    assert len(state["posts"]) == 1


@pytest.mark.parametrize("failure", ["abort", "http_error", "unknown_body"])
def test_browser_never_repeats_a_submission_without_confirmation(
    offline_browser, failure
):
    query, state = offline_browser
    if failure == "abort":
        state["abort"] = True
    elif failure == "http_error":
        state["status"] = 503
    else:
        state["response"] = b"<body>Unknown response</body>"
    issuer = query.lookup_issuer(CNPJ)
    with pytest.raises(AtfSubmissionUncertain):
        query.submit_query(issuer, PERIOD, "xml")
    assert len(state["posts"]) == 1


def test_browser_checks_cancellation_before_official_button(offline_browser):
    query, state = offline_browser
    issuer = query.lookup_issuer(CNPJ)

    def cancelled():
        raise AtfPermissionError("atf_lease_lost")

    query.heartbeat = cancelled
    with pytest.raises(AtfPermissionError, match="atf_lease_lost"):
        query.submit_query(issuer, PERIOD, "txt")
    assert state["posts"] == []


def test_browser_rejects_another_issuer_without_clicking(offline_browser):
    query, state = offline_browser
    query.lookup_issuer(CNPJ)
    with pytest.raises(AtfIdentityMismatch):
        query.submit_query(IssuerIdentity("11111111000111", "42", {}), PERIOD, "xml")
    assert state["posts"] == []


def test_browser_blocks_submission_cancelled_while_waiting_for_button(offline_browser):
    query, state = offline_browser
    issuer = query.lookup_issuer(CNPJ)
    query.prepare_query(issuer, PERIOD, "txt")
    query._call(
        lambda: query._query.page.locator('[name="btnConsultar"]').evaluate(
            """button => {
                button.disabled = true;
                setTimeout(() => { button.disabled = false; }, 200);
            }"""
        )
    )
    checks = []

    def cancelled_after_wait_started():
        checks.append(True)
        if len(checks) > 1:
            raise AtfPermissionError("atf_lease_lost")

    query.heartbeat = cancelled_after_wait_started
    with pytest.raises(AtfPermissionError, match="atf_lease_lost"):
        query.submit_query(issuer, PERIOD, "txt")
    assert len(checks) >= 2
    assert state["posts"] == []


def test_browser_does_not_confirm_a_request_with_changed_filters(offline_browser):
    query, state = offline_browser
    issuer = query.lookup_issuer(CNPJ)
    query._call(
        lambda: query._query.page.locator(
            '[name="btnConsultar"]'
        ).evaluate("""button => {
        button.addEventListener('click', () => {
            document.frmConsultar.edtDtFinal.value = '20/10/2026';
        });
    }""")
    )
    with pytest.raises(AtfSubmissionUncertain):
        query.submit_query(issuer, PERIOD, "xml")
    assert len(state["posts"]) == 1


def test_browser_never_repeats_a_completed_click(offline_browser):
    query, state = offline_browser
    issuer = query.lookup_issuer(CNPJ)
    assert query.submit_query(issuer, PERIOD, "txt").accepted
    with pytest.raises(AtfSubmissionUncertain):
        query.submit_query(issuer, PERIOD, "txt")
    assert len(state["posts"]) == 1


def test_browser_accepts_formatted_cnpj_returned_by_the_portal(offline_browser):
    query, state = offline_browser
    state["masked_issuer"] = True
    issuer = query.lookup_issuer(CNPJ)
    assert query.submit_query(issuer, PERIOD, "txt").accepted
    assert state["posts"][0]["hidCNPJcmpEmit"] == ["00.000.000/0001-91"]
