from datetime import date

from apps.fiscal.atf.types import Period


def test_recovery_preserves_uncertain_submission_without_resetting_to_queued(
    download_company, download_actor
):
    from apps.fiscal.models import DownloadAttempt, RemoteSubmissionBarrier
    from apps.fiscal.services.download_recovery import recover_download_request
    from apps.fiscal.services.downloads import request_download

    request = request_download(
        company_id=download_company.pk,
        period=Period(date(2024, 1, 1), date(2024, 1, 2)),
        formats=("xml",),
        actor_id=download_actor.pk,
        trigger="manual",
        dispatch=False,
    )
    part = request.parts.get()
    part.status = "ambiguous"
    part.save()
    attempt = DownloadAttempt.objects.create(part=part, operation="submit")
    RemoteSubmissionBarrier.objects.create(
        scope="account:pending", part=part, attempt=attempt
    )
    result = recover_download_request(
        request.pk,
        actor_id=download_actor.pk,
        note="Retomar a conciliação",
        dispatch=False,
    )
    part.refresh_from_db()
    assert part.status == "waiting"
    assert RemoteSubmissionBarrier.objects.filter(part=part).exists()
    assert result.resumed_parts == (part.pk,)
