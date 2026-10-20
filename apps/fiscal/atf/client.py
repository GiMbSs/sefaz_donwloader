"""Bounded, certificate-authenticated HTTP client for the SEFAZ-PB portal."""

import hashlib
import os
import re
import tempfile
import time
from contextlib import ExitStack, contextmanager
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlsplit

import requests
from django.conf import settings

from .errors import (
    AtfArtifactError,
    AtfAuthenticationError,
    AtfIdentityMismatch,
    AtfPermissionError,
    AtfPortalChanged,
    AtfSessionExpired,
    AtfSubmissionUncertain,
    AtfTransientError,
)
from .forms import form_fields, parse_issuer, portal_document, visible_text
from .messages import parse_message, parse_message_page
from .profiles import document_profile
from .types import DownloadedArchive, RemoteIdentity, SubmissionReceipt

BASE = "https://www4.sefaz.pb.gov.br"
LOGIN = "/atf/seg/SEGf_LoginSERVirtual.jsp"
QUERY = "/atf/fis/FISf_ConsultarNFeXml2.do"
MAILBOX = "/atf/seg/SEGf_MinhasMensagens.do"


class AtfPbClient:
    def __init__(
        self,
        session: Any,
        company_cnpj: str,
        staging_root: Path,
        *,
        account_key_hint: str | None = None,
    ) -> None:
        if account_key_hint and not re.fullmatch(r"[a-f0-9]{64}", account_key_hint):
            raise AtfPermissionError("atf_invalid_account_namespace")
        self.account_key_hint = account_key_hint
        self.session = session
        self.company_cnpj = company_cnpj
        self.staging_root = staging_root
        self.base_url = getattr(settings, "ATF_PB_BASE_URL", BASE)
        self.identity: RemoteIdentity | None = None
        self.query_fields: dict[str, str] = {}
        self.query_document_model = "55"
        self.mailbox_fields: dict[str, str] = {}
        self.message_fields: dict[str, str] = {}
        self.current_message = None
        self.heartbeat = None
        self.last_heartbeat = 0.0

    def keep_alive(self, *, force: Any = False) -> None:
        current = time.monotonic()
        if self.heartbeat and (force or current - self.last_heartbeat >= 30):
            self.heartbeat()
            self.last_heartbeat = current

    def _url(self, target: str) -> str:
        url = urljoin(self.base_url, target)
        parsed = urlsplit(url)
        if (
            parsed.scheme != "https"
            or parsed.hostname not in {"www4.sefaz.pb.gov.br", "www.sefaz.pb.gov.br"}
            or parsed.port not in {None, 443}
            or parsed.username
            or parsed.password
        ):
            raise AtfPermissionError()
        return url

    def _request(
        self,
        method: Any,
        target: Any,
        *,
        data: Any = None,
        binary: Any = False,
        submission: Any = False,
    ) -> Any:
        url = self._url(target)
        for _ in range(8):
            self.keep_alive(force=True)
            try:
                response = self.session.request(
                    method,
                    url,
                    data=data,
                    allow_redirects=False,
                    stream=True,
                    timeout=(
                        getattr(settings, "ATF_CONNECT_TIMEOUT_SECONDS", 10),
                        getattr(settings, "ATF_READ_TIMEOUT_SECONDS", 60),
                    ),
                )
            except requests.RequestException:
                if submission:
                    raise AtfSubmissionUncertain() from None
                raise AtfTransientError() from None
            status = response.status_code
            if status in {301, 302, 303, 307, 308}:
                location = response.headers.get("Location", "")
                response.close()
                if not location:
                    raise AtfPortalChanged()
                url = self._url(urljoin(url, location))
                if submission and status in {307, 308}:
                    raise AtfSubmissionUncertain()
                if status in {301, 302, 303}:
                    method, data = "GET", None
                continue
            if status != 200:
                response.close()
                if submission:
                    raise AtfSubmissionUncertain()
                if status in {401, 403}:
                    raise (
                        AtfSessionExpired()
                        if self.identity
                        else AtfAuthenticationError()
                    )
                if status == 429 or status >= 500:
                    retry = response.headers.get("Retry-After", "0")
                    try:
                        delay = int(retry)
                    except ValueError:
                        try:
                            delay = int(
                                (
                                    parsedate_to_datetime(retry) - datetime.now(UTC)
                                ).total_seconds()
                            )
                        except (TypeError, ValueError, OverflowError):
                            delay = 0
                    raise AtfTransientError(retry_after_seconds=delay)
                raise AtfPortalChanged()
            if binary:
                return response
            try:
                limit = getattr(settings, "ATF_MAX_HTML_BYTES", 10 * 1024 * 1024)
                chunks, total = [], 0
                for chunk in response.iter_content(chunk_size=65536):
                    self.keep_alive()
                    total += len(chunk)
                    if total > limit:
                        raise AtfPortalChanged("atf_html_limit")
                    chunks.append(chunk)
                response._content = b"".join(chunks)
            except requests.RequestException:
                if submission:
                    raise AtfSubmissionUncertain() from None
                raise AtfTransientError() from None
            finally:
                response.close()
            if self.identity and portal_document(response.content).xpath(
                '//input[@type="password"]'
            ):
                raise AtfSessionExpired()
            return response
        raise AtfPortalChanged("atf_redirect_limit")

    def authenticate(self) -> RemoteIdentity:
        initial = self._request("GET", LOGIN)
        fields = form_fields(initial.content, "FormLogin")
        fields["hidAcao"] = "logarCertificadoDigital"
        response = self._request("POST", LOGIN, data=fields)
        tree = portal_document(response.content)
        text = visible_text(tree)
        login = re.search(r"Login:\s*([\w.@-]+)", text, re.I)
        authenticated_landing = bool(tree.xpath('//form[@name="formMensagens"]'))
        if (
            tree.xpath('//input[@type="password"]')
            or "sair" not in text.lower()
            or (not login and not authenticated_landing)
        ):
            raise AtfAuthenticationError()
        # Some A1 sessions return the authenticated message landing without a
        # Login label. The A1 company is already cryptographically checked by TLS.
        account = "a1:" + self.company_cnpj
        self.identity = RemoteIdentity(
            self.account_key_hint or hashlib.sha256(account.encode()).hexdigest()
        )
        return self.identity

    def lookup_issuer(self, cnpj: Any, *, document_model: str = "55") -> Any:
        profile = document_profile(document_model)
        if cnpj != self.company_cnpj:
            raise AtfIdentityMismatch()
        query = self._request("GET", profile.query_path + "?idSERVirtual=S")
        self.query_fields = form_fields(query.content, "frmConsultar")
        self.query_document_model = document_model
        component = self._request(
            "GET", "/atf/componentes/CodDescLstBS.jsp?id=" + profile.component_id
        )
        fields = form_fields(component.content, "iform")
        fields.update(
            hidAcao="botao",
            hidSqTpDocHumanoInst="2",
            hidTpNatureza="I",
            hidOpcaoListagem="3",
            hidNrInscrEstadual="",
            hidNrDocumentocmpEmit=cnpj,
        )
        result = self._request("POST", "/atf/componentes/CodDescLstBS.jsp", data=fields)
        return parse_issuer(result.content, cnpj)

    def submit_query(
        self, issuer: Any, period: Any, format: Any, *, document_model: str = "55"
    ) -> SubmissionReceipt:
        profile = document_profile(document_model)
        if issuer.cnpj != self.company_cnpj or format not in {"xml", "txt"}:
            raise AtfIdentityMismatch()
        if not self.query_fields or self.query_document_model != document_model:
            raise AtfPortalChanged("atf_missing_query_form")
        fields = {**self.query_fields, **issuer.form_values}
        fields.update(
            hidAcao="consultar",
            edtDtInicial=period.start.strftime("%d/%m/%Y"),
            edtDtFinal=period.end.strftime("%d/%m/%Y"),
            cmbTpExibicao="3" if format == "xml" else "2",
        )
        response = self._request(
            "POST", profile.query_path, data=fields, submission=True
        )
        text = visible_text(portal_document(response.content)).lower()
        if "resultado será enviado para sua caixa de mensagens" not in text:
            raise AtfSubmissionUncertain()
        return SubmissionReceipt(True)

    def list_messages(self, cursor: Any = None, parent_id: Any = None) -> Any:
        target = cursor or MAILBOX
        if parent_id is not None and not str(parent_id).isdigit():
            raise AtfPortalChanged()
        if parent_id and not cursor:
            target += f"?hidsqMensagem={parent_id}"
        response = self._request(
            "POST", target, data={**self.mailbox_fields, "hidAcao": "listar"}
        )
        self.mailbox_fields = form_fields(response.content, "frmMensagens")
        return parse_message_page(response.content, parent_id)

    def read_message(self, message_id: Any, parent_id: Any) -> Any:
        if not str(message_id).isdigit() or not str(parent_id).isdigit():
            raise AtfPortalChanged()
        target = (
            f"/atf/seg/SEGf_LerMensagem.do?hidsqMensagem={message_id}"
            f"&sqMensagemPai={parent_id}"
        )
        response = self._request(
            "POST", target, data={**self.mailbox_fields, "hidAcao": "lerMensagem"}
        )
        self.message_fields = form_fields(response.content, "frmLer")
        parsed = parse_message(response.content, message_id, parent_id)
        self.current_message = message_id
        return parsed

    def download_attachment(self, ref: Any) -> DownloadedArchive:
        if self.current_message != ref.message_id or ref.index < 0:
            raise AtfPermissionError("atf_attachment_context_mismatch")
        response = self._request(
            "POST",
            f"/atf/seg/SEGf_MostrarArquivo.do?hidAnexo={ref.index}",
            data={**self.message_fields, "hidAcao": "mostrarArquivo"},
            binary=True,
        )
        self.staging_root.mkdir(mode=0o700, parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(
            prefix="atf-", suffix=".part", dir=self.staging_root
        )
        target = Path(name)
        digest, total = hashlib.sha256(), 0
        try:
            with os.fdopen(fd, "wb") as stream:
                for chunk in response.iter_content(chunk_size=65536):
                    self.keep_alive()
                    total += len(chunk)
                    if total > getattr(
                        settings, "ATF_MAX_ZIP_BYTES", 200 * 1024 * 1024
                    ):
                        raise AtfArtifactError("atf_zip_limit")
                    digest.update(chunk)
                    stream.write(chunk)
            with target.open("rb") as stream:
                if stream.read(4) not in {b"PK\x03\x04", b"PK\x05\x06"}:
                    raise AtfArtifactError("atf_not_zip")
            return DownloadedArchive(
                target,
                digest.hexdigest(),
                total,
                response.headers.get("Content-Type", ""),
            )
        except requests.RequestException:
            target.unlink(missing_ok=True)
            raise AtfTransientError() from None
        except BaseException:
            target.unlink(missing_ok=True)
            raise
        finally:
            response.close()

    def close(self) -> None:
        self.session.close()


@contextmanager
def open_atf_client(
    company_id: Any, *, heartbeat: Any = None, account_key_hint: str | None = None
) -> Any:
    from apps.certificates.models import DigitalCertificate
    from apps.certificates.services.vault import CertificateVaultError
    from apps.organizations.models import ClientCompany

    from .tls import MutualTlsAdapter, client_tls_context

    if not getattr(settings, "ATF_PB_ENABLED", False):
        raise AtfPermissionError("atf_not_enabled")
    company = ClientCompany.objects.get(
        pk=company_id, status=ClientCompany.Status.ACTIVE
    )
    certificate = (
        DigitalCertificate.objects.filter(company=company, status="active")
        .order_by("-created_at")
        .first()
    )
    if certificate is None:
        raise AtfAuthenticationError("atf_certificate_unavailable")
    with ExitStack() as stack:
        try:
            context = stack.enter_context(client_tls_context(certificate.pk))
        except (CertificateVaultError, OSError, ValueError):
            raise AtfAuthenticationError("atf_certificate_unavailable") from None
        session = stack.enter_context(requests.Session())
        base = getattr(settings, "ATF_PB_BASE_URL", BASE)
        if base != BASE:
            raise AtfPermissionError("atf_base_url_not_approved")
        session.mount(BASE + "/", MutualTlsAdapter(context))
        client = AtfPbClient(
            session,
            company.tax_identifier,
            settings.FISCAL_NOTES_ROOT / ".staging",
            account_key_hint=account_key_hint,
        )
        client.heartbeat = heartbeat
        try:
            client.authenticate()
            yield client
        finally:
            client.close()
