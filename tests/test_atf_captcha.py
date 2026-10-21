from datetime import date

import pytest

from apps.fiscal.atf.client import AtfPbClient
from apps.fiscal.atf.diagnostics import diagnostic_code
from apps.fiscal.atf.errors import AtfPermissionError
from apps.fiscal.atf.types import IssuerIdentity, Period
from tests.test_atf_authentication import Response, Session


@pytest.mark.parametrize("model", ["55", "65"])
def test_widget_presence_does_not_reject_an_otherwise_accepted_query(model, tmp_path):
    source = b"""<form name="frmConsultar"><input name="hidAcao" value="">
    <button name="btnConsultar"
    class="g-recaptcha btn" data-callback="clickConsultar"
    data-sitekey="public-test-key">Consultar</button></form>"""
    issuer = b"""<script>
    parent.frmConsultar.hidSqHumanoInstcmpEmit.value="42";
    parent.frmConsultar.hidCNPJcmpEmit.value="00000000000191";
    </script>"""
    session = Session(
        [
            Response(source),
            Response(b'<form name="iform"></form>'),
            Response(issuer),
            Response("O resultado será enviado para sua caixa de mensagens".encode()),
        ]
    )
    client = AtfPbClient(session, "00000000000191", tmp_path)
    identity = client.lookup_issuer("00000000000191", document_model=model)
    assert client.submit_query(
        identity,
        Period(date(2026, 10, 21), date(2026, 10, 21)),
        "txt",
        document_model=model,
    ).accepted


def test_script_only_3291_response_is_captcha_not_uncertain_submission(tmp_path):
    source = b"""<html><script>var cod = '3291';
    var url = "../seg/SEGf_EmitirMensagemTelaCheia.jsp?codigo=" + cod;
    window.location = url;</script></html>"""
    client = AtfPbClient(Session([Response(source)]), "00000000000191", tmp_path)
    client.query_fields = {"hidAcao": "consultar"}
    with pytest.raises(AtfPermissionError) as error:
        client.submit_query(
            IssuerIdentity("00000000000191", "42", {}),
            Period(date(2026, 10, 21), date(2026, 10, 21)),
            "xml",
        )
    assert diagnostic_code(error.value) == "atf_captcha_required"


@pytest.mark.parametrize("trigger", ["manual", "scheduled"])
@pytest.mark.parametrize("model", ["55", "65"])
def test_captcha_rejection_releases_only_rejected_intent_without_polling(
    download_company, download_actor, tmp_path, trigger, model, monkeypatch
):
    from datetime import time

    from apps.fiscal.atf.errors import AtfCaptchaRequired
    from apps.fiscal.models import DownloadPolicy, RemoteSubmissionBarrier
    from apps.fiscal.services.downloads import advance_part, request_download
    from tests.test_download_execution import Portal

    DownloadPolicy.objects.create(
        company=download_company,
        mode="automatic",
        is_active=True,
        scheduled_time=time(2),
    )

    class CaptchaPortal(Portal):
        def submit_query(self, *args, **kwargs):
            raise AtfCaptchaRequired()

    period = Period(date(2024, 10, 1), date(2024, 10, 1))
    request = request_download(
        company_id=download_company.pk,
        period=period,
        formats=("txt",),
        document_model=model,
        trigger=trigger,
        actor_id=download_actor.pk if trigger == "manual" else None,
        dispatch=False,
    )
    part = request.parts.get()
    portal = CaptchaPortal(tmp_path, period)

    def assert_failure_committed(part, code):
        part.refresh_from_db()
        assert part.status == "failed"
        assert part.error_code == "atf_captcha_required"
        assert part.attempts.get().submission_certainty == "rejected"
        assert not RemoteSubmissionBarrier.objects.filter(part=part).exists()

    monkeypatch.setattr(
        "apps.fiscal.services.downloads._alert", assert_failure_committed
    )
    assert (
        advance_part(part.pk, client_factory=portal.open, dispatch=False).status
        == "failed"
    )
    part.refresh_from_db()
    assert part.error_code == "atf_captcha_required"
    assert part.submitted_at is None
    assert part.next_poll_at is None
    assert part.attempts.get().submission_certainty == "rejected"
    assert not RemoteSubmissionBarrier.objects.filter(part=part).exists()
