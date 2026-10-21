from datetime import date, time, timedelta
from zoneinfo import ZoneInfo

import pytest
from django.utils import timezone

from apps.fiscal.atf.messages import parse_message
from apps.fiscal.atf.types import MessagePage, MessageRef, Period
from apps.fiscal.models import DownloadPolicy, RemoteSubmissionBarrier
from apps.fiscal.services.download_recovery import recover_download_request
from apps.fiscal.services.downloads import advance_part, request_download
from apps.fiscal.services.leases import bind_remote_result
from tests.test_download_execution import Portal


class RealEmptyPortal(Portal):
    root_count = 3
    sent_offset = 0
    sender = "FIS_1322"

    def submit_query(self, *args, **kwargs):
        self.sent = (
            (timezone.now() + timedelta(seconds=self.sent_offset))
            .astimezone(ZoneInfo("America/Fortaleza"))
            .strftime("%d/%m/%Y %H:%M:%S")
        )
        return super().submit_query(*args, **kwargs)

    def list_messages(self, cursor=None, parent_id=None):
        if parent_id:
            return MessagePage(
                tuple(
                    MessageRef(
                        str(int(parent_id) + i),
                        parent_id,
                        self.sender,
                        self.sent,
                        False,
                    )
                    for i in (1, 2, 3)
                )
            )
        return MessagePage(
            tuple(
                MessageRef(root, None, self.sender, self.sent, False, self.root_count)
                for root in self.groups
            )
        )

    def read_message(self, message_id, parent_id):
        index = int(message_id) - int(parent_id)
        text = {
            1: "Iniciando a execução do serviço: Consulta Genérica.",
            2: "Erro durante a execução do método: NFEletronica.gerarTxtXml. "
            "Mensagem: Nenhum registro satisfaz a pesquisa.",
            3: "Finalizando a execução do serviço: Consulta Genérica.",
        }[index]
        return parse_message(
            f"<body>De: {self.sender} Enviada: {self.sent} {text}</body>".encode(),
            message_id,
            parent_id,
        )


@pytest.mark.parametrize("trigger", ["manual", "scheduled"])
@pytest.mark.parametrize("model", ["55", "65"])
@pytest.mark.parametrize("format", ["xml", "txt"])
def test_real_unfiltered_no_records_completes_each_request_kind(
    download_company, download_actor, lifecycle_admin, tmp_path, trigger, model, format
):
    DownloadPolicy.objects.create(
        company=download_company,
        mode="automatic",
        is_active=True,
        scheduled_time=time(2),
    )
    period = Period(date(2024, 10, 1), date(2024, 10, 1))
    request = request_download(
        company_id=download_company.pk,
        period=period,
        formats=(format,),
        trigger=trigger,
        document_model=model,
        actor_id=download_actor.pk if trigger == "manual" else None,
        dispatch=False,
    )
    part = request.parts.get()
    portal = RealEmptyPortal(tmp_path, period)
    portal.sender = "FIS_1484" if model == "65" else "FIS_1322"
    now = timezone.now()
    assert (
        advance_part(
            part.pk, client_factory=portal.open, now=now, dispatch=False
        ).status
        == "waiting"
    )
    assert (
        advance_part(
            part.pk,
            client_factory=portal.open,
            now=now + timedelta(seconds=61),
            dispatch=False,
        ).status
        == "ambiguous"
    )
    part.refresh_from_db()
    assert part.error_code == "atf_empty_requires_review"
    assert RemoteSubmissionBarrier.objects.filter(part=part).exists()
    recovery = recover_download_request(
        request.pk,
        actor_id=download_actor.pk,
        note="Conferir",
        dispatch=False,
    )
    assert recovery.requires_review
    assert recovery.resumed_parts == ()
    bind_remote_result(
        part.pk,
        part.remote_account_key,
        part.candidates[0],
        actor_id=lifecycle_admin.pk,
    )
    assert (
        advance_part(
            part.pk,
            client_factory=portal.open,
            now=now + timedelta(seconds=122),
            dispatch=False,
        ).status
        == "empty"
    )
    request.refresh_from_db()
    assert request.status == "empty"
    assert len(portal.submissions) == 1
    assert not RemoteSubmissionBarrier.objects.filter(part=part).exists()


def test_automatic_binding_is_not_manual_confirmation(
    download_company, download_actor, lifecycle_admin, tmp_path
):
    period = Period(date(2024, 10, 1), date(2024, 10, 1))
    request = request_download(
        company_id=download_company.pk,
        period=period,
        formats=("xml",),
        trigger="manual",
        actor_id=download_actor.pk,
        dispatch=False,
    )
    part = request.parts.get()
    portal = RealEmptyPortal(tmp_path, period)
    now = timezone.now()
    advance_part(part.pk, client_factory=portal.open, now=now, dispatch=False)
    advance_part(
        part.pk,
        client_factory=portal.open,
        now=now + timedelta(seconds=61),
        dispatch=False,
    )
    part.refresh_from_db()
    bind_remote_result(
        part.pk, part.remote_account_key, part.candidates[0], actor_id=None
    )
    assert (
        advance_part(
            part.pk,
            client_factory=portal.open,
            now=now + timedelta(seconds=122),
            dispatch=False,
        ).status
        == "ambiguous"
    )
    bind_remote_result(
        part.pk,
        part.remote_account_key,
        part.candidates[0],
        actor_id=lifecycle_admin.pk,
    )
    assert (
        advance_part(
            part.pk,
            client_factory=portal.open,
            now=now + timedelta(seconds=183),
            dispatch=False,
        ).status
        == "empty"
    )


@pytest.mark.parametrize("count,offset", [(1, 0), (3, -120), (3, 120)])
def test_child_count_or_no_attachment_alone_never_confirms_empty(
    download_company, download_actor, tmp_path, count, offset
):
    period = Period(date(2024, 10, 1), date(2024, 10, 1))
    request = request_download(
        company_id=download_company.pk,
        period=period,
        formats=("txt",),
        trigger="manual",
        actor_id=download_actor.pk,
        dispatch=False,
    )
    part = request.parts.get()
    portal = RealEmptyPortal(tmp_path, period)
    portal.root_count, portal.sent_offset = count, offset
    now = timezone.now()
    advance_part(part.pk, client_factory=portal.open, now=now, dispatch=False)
    assert (
        advance_part(
            part.pk,
            client_factory=portal.open,
            now=now + timedelta(seconds=61),
            dispatch=False,
        ).status
        == "waiting"
    )
