"""Run only NFC-e submissions through the official certificate-authenticated UI."""

import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager, suppress
from typing import Any
from urllib.parse import parse_qs, urlsplit

from django.conf import settings
from playwright.sync_api import (
    BrowserContext,
    Error,
    Page,
    Request,
    Response,
    Route,
    sync_playwright,
)

from apps.certificates.services.vault import CertificateVaultError
from apps.organizations.validators import normalize_tax_identifier

from .browser_session import BrowserSession
from .errors import (
    AtfAuthenticationError,
    AtfCaptchaRequired,
    AtfIdentityMismatch,
    AtfPermissionError,
    AtfPortalChanged,
    AtfSubmissionUncertain,
    AtfTransientError,
)
from .profiles import document_profile
from .submission_response import submission_receipt
from .tls import VerifiedA1, load_verified_a1
from .types import IssuerIdentity, Period, SubmissionReceipt

BASE = "https://www4.sefaz.pb.gov.br"
LOGIN = BASE + "/atf/seg/SEGf_LoginSERVirtual.jsp"
QUERY = document_profile("65").query_path


class NfceBrowserQuery:
    def __init__(
        self, page: Page, company_cnpj: str, *, heartbeat: Callable[[], Any] | None
    ) -> None:
        self.page = page
        self.company_cnpj = company_cnpj
        self.heartbeat = heartbeat
        self.prepared = False
        self.clicked = False
        self.responses: list[Response] = []
        self.expected_fields: dict[str, str] = {}
        self.response_mismatch = False
        self.blocked_submission: Exception | None = None
        self.submission_key: tuple[str, str, Period, str] | None = None
        self.last_heartbeat = 0.0
        self.timeout = max(
            0.1, float(getattr(settings, "ATF_NFCE_BROWSER_TIMEOUT_SECONDS", 120))
        )
        # One blocking operation must leave time to renew the lease.
        self.operation_timeout = (
            min(self.timeout, max(1, settings.ATF_ACCESS_LEASE_SECONDS / 2)) * 1000
        )
        page.set_default_timeout(self.operation_timeout)
        page.set_default_navigation_timeout(self.operation_timeout)
        page.on("requestfinished", self._finished)

    def _finished(self, request: Request) -> None:
        response = request.response()
        if response is not None:
            self._response(response)

    def _alive(self, *, force: bool = False) -> None:
        now = time.monotonic()
        if self.heartbeat and (force or now - self.last_heartbeat >= 5):
            self.heartbeat()
            self.last_heartbeat = now

    def _response(self, response: Response) -> None:
        request = response.request
        if (
            self.clicked
            and urlsplit(response.url).scheme == "https"
            and urlsplit(response.url).netloc == "www4.sefaz.pb.gov.br"
            and urlsplit(response.url).path == QUERY
            and request.method == "POST"
            and parse_qs(request.post_data or "").get("hidAcao") == ["consultar"]
        ):
            # No ORM or logging in Playwright's event-loop callbacks.
            values = parse_qs(request.post_data or "")
            if any(
                values.get(key) != [value]
                for key, value in self.expected_fields.items()
            ):
                self.response_mismatch = True
            self.responses.append(response)

    def _wait(self, condition: Callable[[], bool]) -> None:
        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            self._alive()
            if condition():
                return
            self.page.wait_for_timeout(200)
        raise AtfTransientError("atf_nfce_browser_timeout")

    def _authorize_submission(self, route: Route) -> None:
        request = route.request
        if request.method == "POST" and self.clicked:
            # The official click/reCAPTCHA callback can wait before sending.
            # Recheck cancellation/lease at dispatch, on the Django caller thread.
            try:
                self._alive(force=True)
            except Exception as error:
                self.blocked_submission = error
                route.abort()
                return
        route.fallback()

    def lookup_issuer(self, cnpj: str) -> IssuerIdentity:
        if cnpj != self.company_cnpj:
            raise AtfIdentityMismatch()
        try:
            self._alive(force=True)
            self.page.goto(LOGIN, wait_until="domcontentloaded")
            self._alive()
            self.page.get_by_text("Acesso via Certificado Digital", exact=False).click()
            self._wait(
                lambda: bool(
                    self.page.locator(
                        'form[name="formMensagens"], a:has-text("Sair")'
                    ).count()
                )
            )
            self._alive()
            self.page.goto(
                BASE + QUERY + "?idSERVirtual=S", wait_until="domcontentloaded"
            )
            self._alive()
            self.page.locator('select[name="cmbTpDoccmpEmit"]').select_option("2")
            self._alive(force=True)
            frame = self.page.frame_locator('iframe[name="cmpEmit"]')
            frame.locator('input[name="hidNrDocumentocmpEmit"]').fill(cnpj)
            self._alive(force=True)
            frame.locator('[name="btnPesquisar"]').click()
            self._wait(
                lambda: (
                    normalize_tax_identifier(
                        self.page.locator('input[name="hidCNPJcmpEmit"]').input_value()
                    )
                    == cnpj
                )
            )
            remote_id = self.page.locator(
                'input[name="hidSqHumanoInstcmpEmit"]'
            ).input_value()
            if not remote_id.isdigit():
                raise AtfPortalChanged("atf_nfce_browser_contract")
            self.prepared = True
            return IssuerIdentity(cnpj, remote_id, {})
        except Error:
            raise AtfTransientError("atf_nfce_browser_timeout") from None

    def prepare_query(
        self, issuer: IssuerIdentity, period: Period, format: str
    ) -> None:
        if issuer.cnpj != self.company_cnpj or format not in {"xml", "txt"}:
            raise AtfIdentityMismatch()
        if not self.prepared:
            raise AtfPortalChanged("atf_nfce_browser_contract")
        if self.clicked:
            raise AtfSubmissionUncertain()
        try:
            self._alive(force=True)
            self.page.locator('input[name="edtDtInicial"]').fill(
                period.start.strftime("%d/%m/%Y")
            )
            self._alive(force=True)
            self.page.locator('input[name="edtDtFinal"]').fill(
                period.end.strftime("%d/%m/%Y")
            )
            self._alive(force=True)
            self.page.locator('select[name="cmbTpExibicao"]').select_option(
                "3" if format == "xml" else "2"
            )
            self._alive(force=True)
            self.expected_fields = {
                "edtDtInicial": period.start.strftime("%d/%m/%Y"),
                "edtDtFinal": period.end.strftime("%d/%m/%Y"),
                "cmbTpExibicao": "3" if format == "xml" else "2",
                "cmbTpDoccmpEmit": "2",
                "hidCNPJcmpEmit": self.page.locator(
                    'input[name="hidCNPJcmpEmit"]'
                ).input_value(),
                "hidSqHumanoInstcmpEmit": issuer.remote_id,
            }
            if (
                normalize_tax_identifier(self.expected_fields["hidCNPJcmpEmit"])
                != self.company_cnpj
            ):
                raise AtfIdentityMismatch()
            observed_id = self.page.locator(
                'input[name="hidSqHumanoInstcmpEmit"]'
            ).input_value()
            if observed_id != issuer.remote_id:
                raise AtfIdentityMismatch()
            self.submission_key = (issuer.cnpj, issuer.remote_id, period, format)
        except Error:
            raise AtfTransientError("atf_nfce_browser_timeout") from None

    def submit_query(
        self, issuer: IssuerIdentity, period: Period, format: str
    ) -> SubmissionReceipt:
        if self.clicked:
            raise AtfSubmissionUncertain()
        if self.submission_key != (issuer.cnpj, issuer.remote_id, period, format):
            self.prepare_query(issuer, period, format)
        try:
            self._alive(force=True)
            self.page.route(BASE + QUERY + "*", self._authorize_submission)
            self.clicked = True
            self.page.locator('[name="btnConsultar"]').click(no_wait_after=True)
            deadline = time.monotonic() + self.timeout
            while (
                not self.responses
                and self.blocked_submission is None
                and time.monotonic() < deadline
            ):
                self._alive()
                self.page.wait_for_timeout(200)
            if self.blocked_submission is not None:
                raise self.blocked_submission
            if not self.responses or self.response_mismatch:
                raise AtfSubmissionUncertain()
            response = self.responses[0]
            if response.status != 200:
                raise AtfSubmissionUncertain()
            content = response.body()
            if len(content) > getattr(settings, "ATF_MAX_HTML_BYTES", 10 * 1024 * 1024):
                raise AtfSubmissionUncertain()
            return submission_receipt(content)
        except Error:
            if self.blocked_submission is not None:
                raise self.blocked_submission from None
            url = urlsplit(self.page.url)
            if (
                self.clicked
                and url.scheme == "https"
                and url.netloc == "www4.sefaz.pb.gov.br"
                and url.path == "/atf/seg/SEGf_EmitirMensagemTelaCheia.jsp"
                and parse_qs(url.query).get("codigo") == ["3291"]
            ):
                raise AtfCaptchaRequired() from None
            if self.clicked:
                raise AtfSubmissionUncertain() from None
            raise AtfTransientError("atf_nfce_browser_timeout") from None


@contextmanager
def _open_browser(
    material: VerifiedA1, *, heartbeat: Callable[[], Any] | None
) -> Iterator[NfceBrowserQuery]:
    driver = None
    browser = None
    context: BrowserContext | None = None
    try:
        try:
            driver = sync_playwright().start()
            browser = driver.chromium.launch(
                headless=True,
                timeout=max(1000, settings.ATF_CONNECT_TIMEOUT_SECONDS * 1000),
            )
            context = browser.new_context(
                locale="pt-BR",
                accept_downloads=False,
                client_certificates=[
                    {
                        "origin": BASE,
                        "pfx": material.pfx,
                        "passphrase": material.passphrase,
                    }
                ],
            )
            page = context.new_page()
        except Error:
            raise AtfPermissionError("atf_nfce_browser_unavailable") from None
        company_cnpj = material.company_cnpj
        del material
        yield NfceBrowserQuery(page, company_cnpj, heartbeat=heartbeat)
    finally:
        # Cleanup never replaces the accepted/uncertain result with a new failure.
        for resource in (context, browser):
            if resource is not None:
                with suppress(Error):
                    resource.close()
        if driver is not None:
            with suppress(Error):
                driver.stop()


@contextmanager
def open_nfce_query(
    certificate_id: int, *, heartbeat: Callable[[], Any] | None = None
) -> Iterator[BrowserSession]:
    try:
        # Database and vault access stay on the worker's original thread.
        material = load_verified_a1(certificate_id)
    except (CertificateVaultError, ValueError, OSError):
        raise AtfAuthenticationError("atf_certificate_unavailable") from None
    session = BrowserSession(
        lambda pulse: _open_browser(material, heartbeat=pulse), heartbeat=heartbeat
    )
    try:
        yield session
    finally:
        session.close()
