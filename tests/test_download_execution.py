from contextlib import contextmanager
from datetime import date, timedelta

from django.utils import timezone

from apps.fiscal.atf.types import (
    AttachmentRef,
    IssuerIdentity,
    MessagePage,
    MessageRef,
    ParsedMessage,
    Period,
    RemoteIdentity,
    SubmissionReceipt,
)
from tests.test_download_archives import INVOICE, KEY, archive_file


class Portal:
    def __init__(self, folder, period, uncertain=False):
        self.folder = folder
        self.period = period
        self.identity = RemoteIdentity("a" * 64)
        self.submissions = []
        self.groups = {}
        self.uncertain = uncertain

    @contextmanager
    def open(self, company_id):
        yield self

    def lookup_issuer(self, cnpj, *, document_model="55"):
        return IssuerIdentity(cnpj, "42", {"hidSqHumanoInstcmpEmit": "42"})

    def list_messages(self, cursor=None, parent_id=None):
        if parent_id:
            return MessagePage(
                (MessageRef(str(int(parent_id) + 1), parent_id, "FIS_1322", "", True),)
            )
        return MessagePage(
            tuple(
                MessageRef(group, None, "FIS_1322", "", False, 1)
                for group in self.groups
            )
        )

    def submit_query(self, issuer, period, format, *, document_model="55"):
        self.submissions.append((period, format))
        self.groups[str(100 + len(self.submissions) * 10)] = format
        if self.uncertain:
            from apps.fiscal.atf.errors import AtfSubmissionUncertain

            raise AtfSubmissionUncertain()
        return SubmissionReceipt(True)

    def read_message(self, message_id, parent_id):
        self.current_group = parent_id
        return ParsedMessage(
            MessageRef(message_id, parent_id, "FIS_1322", "", True),
            self.period,
            (AttachmentRef(message_id, 0),),
            "success",
        )

    def download_attachment(self, ref):
        format = self.groups[self.current_group]
        payload = (
            INVOICE
            if format == "xml"
            else (
                "Chave_de_acesso|Numero|Data_de_emissao|CPF_CNPJ_emit\n"
                f"{KEY}|1|10/10/2024|00000000000191\n"
            ).encode()
        )
        return archive_file(self.folder, [(f"data.{format}", payload)])


def test_request_creation_coalesces_active_double_click(
    download_company, download_actor
):
    from apps.fiscal.services.downloads import request_download

    period = Period(date(2024, 10, 1), date(2024, 10, 18))
    first = request_download(
        company_id=download_company.pk,
        period=period,
        formats=("xml", "txt"),
        actor_id=download_actor.pk,
        trigger="manual",
        dispatch=False,
    )
    second = request_download(
        company_id=download_company.pk,
        period=period,
        formats=("txt", "xml"),
        actor_id=download_actor.pk,
        trigger="manual",
        dispatch=False,
    )
    assert first.pk == second.pk
    assert first.parts.count() == 2


def test_download_restarts_from_waiting_and_delivers_both_formats(
    tmp_path, download_company, download_actor, settings
):
    from apps.fiscal.services.downloads import advance_part, request_download

    settings.FISCAL_NOTES_ROOT = tmp_path / "notes"
    period = Period(date(2024, 10, 1), date(2024, 10, 18))
    portal = Portal(tmp_path, period)
    request = request_download(
        company_id=download_company.pk,
        period=period,
        formats=("xml", "txt"),
        actor_id=download_actor.pk,
        trigger="manual",
        dispatch=False,
    )
    now = timezone.now()
    for part in request.parts.all():
        result = advance_part(
            part.pk, client_factory=portal.open, now=now, dispatch=False
        )
        assert result.status == "waiting"
        now += timedelta(seconds=61)
        result = advance_part(
            part.pk, client_factory=portal.open, now=now, dispatch=False
        )
        assert result.status == "succeeded"
        now += timedelta(seconds=61)
    request.refresh_from_db()
    assert request.status == "succeeded"
    assert len(portal.submissions) == 2
    assert sum(part.archives.count() for part in request.parts.all()) == 2


def test_timeout_after_accepted_post_never_resubmits(
    tmp_path, download_company, download_actor, settings
):
    from apps.fiscal.models import RemoteSubmissionBarrier
    from apps.fiscal.services.downloads import advance_part, request_download

    settings.FISCAL_NOTES_ROOT = tmp_path / "notes"
    period = Period(date(2024, 10, 1), date(2024, 10, 18))
    portal = Portal(tmp_path, period, uncertain=True)
    request = request_download(
        company_id=download_company.pk,
        period=period,
        formats=("xml",),
        actor_id=download_actor.pk,
        trigger="manual",
        dispatch=False,
    )
    part = request.parts.get()
    now = timezone.now()
    advance_part(part.pk, client_factory=portal.open, now=now, dispatch=False)
    part.refresh_from_db()
    assert part.status == "ambiguous"
    assert RemoteSubmissionBarrier.objects.filter(part=part).count() == 2
    advance_part(
        part.pk,
        client_factory=portal.open,
        now=now + timedelta(seconds=61),
        dispatch=False,
    )
    assert len(portal.submissions) == 1
    part.refresh_from_db()
    assert part.status == "succeeded"
    assert not RemoteSubmissionBarrier.objects.filter(part=part).exists()


def test_missing_certificate_finishes_with_safe_error_without_network(
    download_company, download_actor, monkeypatch, settings
):
    import pytest

    from apps.fiscal.services.downloads import advance_part, request_download

    settings.ATF_PB_ENABLED = True
    monkeypatch.setattr(
        "socket.create_connection",
        lambda *args, **kwargs: pytest.fail("No network without A1"),
    )
    request = request_download(
        company_id=download_company.pk,
        period=Period(date(2024, 10, 1), date(2024, 10, 18)),
        formats=("xml",),
        actor_id=download_actor.pk,
        trigger="manual",
        dispatch=False,
    )
    result = advance_part(request.parts.get().pk, dispatch=False)
    assert result.status == "failed"
    assert request.parts.get().error_code == "atf_authentication_failed"


def test_inactive_company_cannot_submit_new_query(
    tmp_path, download_company, download_actor
):
    from apps.fiscal.services.downloads import advance_part, request_download

    period = Period(date(2024, 10, 1), date(2024, 10, 18))
    request = request_download(
        company_id=download_company.pk,
        period=period,
        formats=("xml",),
        actor_id=download_actor.pk,
        trigger="manual",
        dispatch=False,
    )
    download_company.status = "inactive"
    download_company.save(update_fields=["status"])
    portal = Portal(tmp_path, period)
    assert (
        advance_part(
            request.parts.get().pk, client_factory=portal.open, dispatch=False
        ).status
        == "failed"
    )
    assert portal.submissions == []


def test_scheduled_transient_exhaustion_defers_same_part_without_resubmission(
    tmp_path, download_company, settings
):
    from apps.fiscal.atf.errors import AtfTransientError
    from apps.fiscal.models import DownloadPolicy, RemoteSubmissionBarrier
    from apps.fiscal.services.downloads import advance_part, request_download

    DownloadPolicy.objects.create(
        company=download_company, mode="automatic", is_active=True
    )
    period = Period(date(2024, 10, 1), date(2024, 10, 18))
    portal = Portal(tmp_path, period)
    request = request_download(
        company_id=download_company.pk,
        period=period,
        formats=("xml",),
        actor_id=None,
        trigger="scheduled",
        dispatch=False,
    )
    part = request.parts.get()
    now = timezone.now()
    advance_part(part.pk, client_factory=portal.open, now=now, dispatch=False)

    def slow(*args, **kwargs):
        raise AtfTransientError()

    portal.list_messages = slow
    part.refresh_from_db()
    part.retry_count = 3
    part.save(update_fields=["retry_count"])
    result = advance_part(
        part.pk,
        client_factory=portal.open,
        now=now + timedelta(seconds=61),
        dispatch=False,
    )
    part.refresh_from_db()
    request.refresh_from_db()
    assert result.status == "waiting"
    assert part.retry_cycle == 1
    assert part.retry_count == 0
    assert part.next_poll_at >= now + timedelta(minutes=30)
    assert request.status == "waiting"
    assert len(portal.submissions) == 1
    assert RemoteSubmissionBarrier.objects.filter(part=part).count() == 2


def test_manual_exhaustion_does_not_enter_long_automatic_retry(
    download_company, download_actor
):
    from apps.fiscal.atf.errors import AtfTransientError
    from apps.fiscal.services.downloads import advance_part, request_download

    @contextmanager
    def offline(company_id):
        raise AtfTransientError()
        yield

    request = request_download(
        company_id=download_company.pk,
        period=Period(date(2024, 10, 1), date(2024, 10, 18)),
        formats=("xml",),
        actor_id=download_actor.pk,
        trigger="manual",
        dispatch=False,
    )
    part = request.parts.get()
    part.retry_count = 3
    part.save(update_fields=["retry_count"])
    assert (
        advance_part(part.pk, client_factory=offline, dispatch=False).status == "failed"
    )
    assert request.parts.get().retry_cycle == 0


def test_denied_lease_cannot_overwrite_a_concurrent_completion(
    download_company, download_actor, monkeypatch
):
    from apps.fiscal.models import DownloadPart, DownloadRequest
    from apps.fiscal.services.downloads import advance_part, request_download

    request = request_download(
        company_id=download_company.pk,
        period=Period(date(2024, 10, 1), date(2024, 10, 18)),
        formats=("xml",),
        actor_id=download_actor.pk,
        trigger="manual",
        dispatch=False,
    )
    part = request.parts.get()

    def completed_by_other_owner(*args, **kwargs):
        DownloadPart.objects.filter(pk=part.pk).update(status="succeeded")
        DownloadRequest.objects.filter(pk=request.pk).update(status="succeeded")
        return None

    monkeypatch.setattr(
        "apps.fiscal.services.downloads.claim_access", completed_by_other_owner
    )
    advance_part(part.pk, dispatch=False)
    assert request.parts.get().status == "succeeded"
    request.refresh_from_db()
    assert request.status == "succeeded"
