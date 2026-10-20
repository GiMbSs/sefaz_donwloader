from datetime import date, time, timedelta

import pytest
from django.utils import timezone

from apps.fiscal.atf.types import Period
from tests.test_download_archives import INVOICE, KEY, archive_file
from tests.test_download_execution import Portal

NFCE_KEY = KEY[:20] + "65" + KEY[22:]
NFCE_XML = INVOICE.replace(KEY.encode(), NFCE_KEY.encode()).replace(
    b"<mod>55</mod>", b"<mod>65</mod>"
)


class NfcePortal(Portal):
    ready = False

    def list_messages(self, cursor=None, parent_id=None):
        from apps.fiscal.atf.types import MessagePage, MessageRef

        if parent_id:
            return MessagePage(
                tuple(
                    MessageRef(
                        str(int(parent_id) + i), parent_id, "FIS_1484", "", False
                    )
                    for i in (1, 2)
                )
            )
        return MessagePage(
            tuple(
                MessageRef(group, None, "FIS_1484", "", False, 2)
                for group in self.groups
            )
        )

    def read_message(self, message_id, parent_id):
        from apps.fiscal.atf.types import AttachmentRef, MessageRef, ParsedMessage

        self.current_group = parent_id
        initial = message_id == str(int(parent_id) + 1)
        attachments = (
            ()
            if initial or not self.ready
            else (AttachmentRef(message_id, 0), AttachmentRef(message_id, 1))
        )
        return ParsedMessage(
            MessageRef(message_id, parent_id, "FIS_1484", "", bool(attachments)),
            None if initial else self.period,
            attachments,
            "success" if attachments else "pending",
            {"processing": "true"} if not initial and not self.ready else {},
        )

    def download_attachment(self, ref):
        fmt = self.groups[self.current_group]
        payload = (
            NFCE_XML
            if fmt == "xml"
            else (
                "Chave_de_acesso|Numero|Data_de_emissao|CPF_CNPJ_emit\n"
                f"{NFCE_KEY}|1|10/10/2024|00000000000191\n"
            ).encode()
        )
        return archive_file(self.folder, [(f"data-{ref.index}.{fmt}", payload)])


def test_nfce_and_nfe_requests_do_not_coalesce(download_company, download_actor):
    from apps.fiscal.services.downloads import request_download

    values = dict(
        company_id=download_company.pk,
        period=Period(date(2024, 10, 1), date(2024, 10, 3)),
        formats=("xml", "txt"),
        actor_id=download_actor.pk,
        trigger="manual",
        dispatch=False,
    )
    nfe = request_download(**values)
    nfce = request_download(**values, document_model="65")
    repeated = request_download(**values, document_model="65")
    assert nfe.pk != nfce.pk
    assert repeated.pk == nfce.pk
    assert nfce.document_model == "65"
    assert nfce.parts.count() == 6
    assert set(nfce.parts.values_list("start_date", "end_date")) == {
        (date(2024, 10, day), date(2024, 10, day)) for day in (1, 2, 3)
    }
    assert nfe.parts.count() == 2


def test_policy_can_schedule_both_models(download_company, settings):
    from datetime import UTC, datetime

    from apps.fiscal.models import DownloadPolicy
    from apps.fiscal.services.scheduling import enqueue_due_downloads

    settings.ATF_PB_ENABLED = True
    policy = DownloadPolicy(
        company=download_company,
        mode="automatic",
        is_active=True,
        scheduled_time=time(2),
        document_models=["55", "65"],
    )
    policy.full_clean()
    policy.save()
    enqueue_due_downloads(now=datetime(2024, 10, 11, 6, tzinfo=UTC), dispatch=False)
    assert set(
        download_company.download_requests.values_list("document_model", flat=True)
    ) == {"55", "65"}


def test_unknown_document_model_is_rejected_before_creating_request(
    download_company, download_actor
):
    from django.core.exceptions import ValidationError

    from apps.fiscal.services.downloads import request_download

    with pytest.raises((ValidationError, ValueError)):
        request_download(
            company_id=download_company.pk,
            period=Period(date(2024, 10, 1), date(2024, 10, 1)),
            document_model="57",
            formats=("xml",),
            actor_id=download_actor.pk,
            trigger="manual",
            dispatch=False,
        )
    assert not download_company.download_requests.exists()


@pytest.mark.parametrize("uncertain", [False, True])
def test_nfce_waits_days_for_an_attachment_without_resubmitting(
    download_company, download_actor, tmp_path, settings, uncertain
):
    from apps.fiscal.models import RemoteSubmissionBarrier
    from apps.fiscal.services.downloads import advance_part, request_download

    settings.FISCAL_NOTES_ROOT = tmp_path / "notes"
    period = Period(date(2024, 10, 10), date(2024, 10, 10))
    portal = NfcePortal(tmp_path, period, uncertain=uncertain)
    request = request_download(
        company_id=download_company.pk,
        period=period,
        formats=("xml",),
        document_model="65",
        actor_id=download_actor.pk,
        trigger="manual",
        dispatch=False,
    )
    part = request.parts.get()
    now = timezone.now()
    advance_part(part.pk, client_factory=portal.open, now=now, dispatch=False)
    part.refresh_from_db()
    assert part.deadline_at >= now + timedelta(days=7)
    result = advance_part(
        part.pk,
        client_factory=portal.open,
        now=now + timedelta(hours=25),
        dispatch=False,
    )
    assert result.status == "waiting"
    assert RemoteSubmissionBarrier.objects.filter(part=part).count() == 2
    portal.ready = True
    result = advance_part(
        part.pk, client_factory=portal.open, now=now + timedelta(days=2), dispatch=False
    )
    assert result.status == "succeeded"
    assert len(portal.submissions) == 1
    assert part.archives.count() == 2
    assert download_company.invoices.get().model == "65"
    assert download_company.invoices.get().number == 1


def test_nfce_polling_backoff_survives_worker_restarts(
    download_company, download_actor, tmp_path
):
    from apps.fiscal.services.downloads import advance_part, request_download

    period = Period(date(2024, 10, 10), date(2024, 10, 10))
    portal = NfcePortal(tmp_path, period)
    request = request_download(
        company_id=download_company.pk,
        period=period,
        formats=("xml",),
        document_model="65",
        actor_id=download_actor.pk,
        trigger="manual",
        dispatch=False,
    )
    part = request.parts.get()
    now = timezone.now()
    result = advance_part(part.pk, client_factory=portal.open, now=now, dispatch=False)
    delays = []
    for _ in range(5):
        now = result.next_eta + timedelta(seconds=1)
        result = advance_part(
            part.pk, client_factory=portal.open, now=now, dispatch=False
        )
        delays.append((result.next_eta - now).total_seconds())
    assert delays[-1] > delays[0] >= 60
    assert len(portal.submissions) == 1
