from datetime import date, time, timedelta

import pytest
from django.utils import timezone

from apps.fiscal.atf.types import Period
from apps.fiscal.models import DownloadPolicy, RemoteSubmissionBarrier
from apps.fiscal.services.downloads import advance_part, request_download
from tests.test_download_execution import Portal
from tests.test_nfce_downloads import NfcePortal


@pytest.mark.parametrize("owner_model", ["55", "65"])
def test_queued_query_cannot_starve_pending_mailbox_result(
    download_company, tmp_path, settings, owner_model, caplog
):
    """The next request must not take every poll slot from the pending one."""
    settings.FISCAL_NOTES_ROOT = tmp_path / "notes"
    caplog.set_level("INFO", logger="apps.fiscal.services.downloads")
    DownloadPolicy.objects.create(
        company=download_company,
        mode="automatic",
        is_active=True,
        scheduled_time=time(2),
        document_models=["55", "65"],
        formats=["txt"],
    )
    period = Period(date(2024, 10, 1), date(2024, 10, 18))

    def create(model):
        return request_download(
            company_id=download_company.pk,
            period=period,
            formats=("txt",),
            document_model=model,
            actor_id=None,
            trigger="scheduled",
            dispatch=False,
        ).parts.get()

    owner = create(owner_model)
    queued = create("65" if owner_model == "55" else "55")
    owner_portal = (Portal if owner_model == "55" else NfcePortal)(tmp_path, period)
    owner_portal.ready = True

    class NextPortal(NfcePortal if owner_model == "55" else Portal):
        def submit_query(self, *args, **kwargs):
            receipt = super().submit_query(*args, **kwargs)
            # Root message identifiers are unique across this shared account.
            self.groups = {
                str(int(key) + 1000): fmt for key, fmt in self.groups.items()
            }
            return receipt

    queued_portal = NextPortal(tmp_path, period)
    queued_portal.ready = True
    now = timezone.now()
    assert (
        advance_part(
            owner.pk, client_factory=owner_portal.open, now=now, dispatch=False
        ).status
        == "waiting"
    )

    # The queued delivery wins the local lock immediately before the owner.
    # It must leave the mailbox interval available to reconcile the owner.
    for seconds in (61, 122, 183):
        advance_part(
            queued.pk,
            client_factory=queued_portal.open,
            now=now + timedelta(seconds=seconds),
            dispatch=False,
        )
        result = advance_part(
            owner.pk,
            client_factory=owner_portal.open,
            now=now + timedelta(seconds=seconds + 1),
            dispatch=False,
        )
        if result.status == "succeeded":
            break
    assert result.status == "succeeded"
    assert len(owner_portal.submissions) == 1
    assert not queued_portal.submissions
    assert "reason=submission_pending" in caplog.text
    assert f"blocking_part_id={owner.pk}" in caplog.text
    assert not RemoteSubmissionBarrier.objects.filter(part=owner).exists()

    # Without creating a replacement request, the queued query can now run.
    later = now + timedelta(minutes=5)
    assert (
        advance_part(
            queued.pk, client_factory=queued_portal.open, now=later, dispatch=False
        ).status
        == "waiting"
    )
    assert (
        advance_part(
            queued.pk,
            client_factory=queued_portal.open,
            now=later + timedelta(seconds=61),
            dispatch=False,
        ).status
        == "succeeded"
    )
    assert len(queued_portal.submissions) == 1
