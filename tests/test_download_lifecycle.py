from datetime import timedelta

import pytest
from django.core.exceptions import PermissionDenied, ValidationError
from django.utils import timezone

from apps.fiscal.atf.errors import AtfPermissionError, AtfTransientError
from apps.fiscal.atf.types import Period
from apps.fiscal.models import DownloadAttempt, RemoteSubmissionBarrier
from apps.fiscal.services.download_lifecycle import (
    cancel_download_request,
    delete_cancelled_download_request,
)
from apps.fiscal.services.download_recovery import recover_download_request
from apps.fiscal.services.downloads import advance_part
from apps.fiscal.services.leases import assert_access, claim_access, company_scope
from apps.operations.models import AuditLog
from apps.organizations.models import OfficeMembership
from tests.test_download_execution import Portal
from tests.test_nfce_downloads import NfcePortal


def cancel(request, actor, **kwargs):
    return cancel_download_request(
        request.pk,
        actor_id=actor.pk,
        note="Encerramento administrativo de teste",
        acknowledge_remote_uncertainty=True,
        **kwargs,
    )


def test_cancel_stops_all_unfinished_parts_and_releases_barriers(
    lifecycle_request, lifecycle_admin
):
    request = lifecycle_request
    part = request.parts.first()
    part.status = "waiting"
    part.submitted_at = timezone.now()
    part.next_poll_at = timezone.now() + timedelta(minutes=1)
    part.save()
    attempt = DownloadAttempt.objects.create(part=part, operation="submit")
    RemoteSubmissionBarrier.objects.create(
        scope=company_scope(request.company.tax_identifier), part=part, attempt=attempt
    )
    token = claim_access("account:test-cancel", part.pk, now=timezone.now())
    cancel(request, lifecycle_admin)
    request.refresh_from_db()
    assert request.status == "cancelled"
    assert request.finished_at is not None
    assert set(request.parts.values_list("status", flat=True)) == {"cancelled"}
    assert not request.parts.filter(next_poll_at__isnull=False).exists()
    assert not RemoteSubmissionBarrier.objects.filter(part__request=request).exists()
    with pytest.raises(AtfPermissionError):
        assert_access(token, now=timezone.now())
    cancel(request, lifecycle_admin)
    assert AuditLog.objects.filter(action="fiscal.download_cancelled").count() == 1
    with pytest.raises(ValidationError):
        recover_download_request(
            request.pk, actor_id=lifecycle_admin.pk, note="Não reabrir"
        )


@pytest.mark.parametrize("permission", ["operator", "inactive", "outsider"])
@pytest.mark.parametrize("operation", ["cancel", "delete"])
def test_lifecycle_service_requires_active_admin_in_same_office(
    lifecycle_request, lifecycle_admin, permission, operation
):
    if operation == "delete":
        cancel(lifecycle_request, lifecycle_admin)
    membership = OfficeMembership.objects.get(user=lifecycle_admin)
    if permission == "operator":
        membership.role = "operator"
        membership.save()
    elif permission == "inactive":
        lifecycle_admin.is_active = False
        lifecycle_admin.save()
    else:
        membership.delete()
    with pytest.raises(PermissionDenied):
        if operation == "cancel":
            cancel(lifecycle_request, lifecycle_admin)
        else:
            delete_cancelled_download_request(
                lifecycle_request.pk, actor_id=lifecycle_admin.pk, note="Excluir"
            )


def test_superuser_can_cancel_without_office_membership(
    lifecycle_request, lifecycle_admin
):
    OfficeMembership.objects.filter(user=lifecycle_admin).delete()
    lifecycle_admin.is_superuser = True
    lifecycle_admin.save()
    cancel(lifecycle_request, lifecycle_admin)
    lifecycle_request.refresh_from_db()
    assert lifecycle_request.status == "cancelled"


def test_confirmation_and_reason_are_required(lifecycle_request, lifecycle_admin):
    for note, acknowledge in [("", True), ("   ", True), ("Motivo", False)]:
        with pytest.raises(ValidationError):
            cancel_download_request(
                lifecycle_request.pk,
                actor_id=lifecycle_admin.pk,
                note=note,
                acknowledge_remote_uncertainty=acknowledge,
            )
    lifecycle_request.refresh_from_db()
    assert lifecycle_request.status == "queued"
    with pytest.raises(ValidationError):
        delete_cancelled_download_request(
            lifecycle_request.pk, actor_id=lifecycle_admin.pk, note="Excluir ativo"
        )


@pytest.mark.parametrize("model", ["55", "65"])
@pytest.mark.parametrize(
    "phase", ["prepare", "submit", "poll", "download", "error", "transient"]
)
def test_running_worker_cannot_resume_or_publish_after_cancel(
    lifecycle_request, lifecycle_admin, tmp_path, settings, model, phase
):
    settings.FISCAL_NOTES_ROOT = tmp_path / "notes"
    request = lifecycle_request
    request.document_model = model
    request.save()
    part = request.parts.get(format="xml")
    period = Period(part.start_date, part.end_date)
    base = Portal if model == "55" else NfcePortal

    class CancelDuringWork(base):
        ready = True

        def lookup_issuer(self, *args, **kwargs):
            if phase == "prepare":
                cancel(request, lifecycle_admin)
            return super().lookup_issuer(*args, **kwargs)

        def submit_query(self, *args, **kwargs):
            receipt = super().submit_query(*args, **kwargs)
            if phase in {"submit", "error", "transient"}:
                cancel(request, lifecycle_admin)
                if phase == "error":
                    raise RuntimeError("Synthetic submission failure")
                if phase == "transient":
                    raise AtfTransientError()
            return receipt

        def read_message(self, *args, **kwargs):
            message = super().read_message(*args, **kwargs)
            if phase == "poll":
                cancel(request, lifecycle_admin)
            return message

        def download_attachment(self, *args, **kwargs):
            download = super().download_attachment(*args, **kwargs)
            if phase == "download":
                cancel(request, lifecycle_admin)
            return download

    portal = CancelDuringWork(tmp_path, period)
    now = timezone.now()
    result = advance_part(part.pk, client_factory=portal.open, now=now, dispatch=False)
    if phase in {"poll", "download"}:
        assert result.status == "waiting"
        result = advance_part(
            part.pk,
            client_factory=portal.open,
            now=now + timedelta(minutes=2),
            dispatch=False,
        )
    assert result.status == "cancelled"
    part.refresh_from_db()
    request.refresh_from_db()
    assert request.status == part.status == "cancelled"
    assert part.next_poll_at is None
    assert not part.archives.exists()
    assert not RemoteSubmissionBarrier.objects.filter(part__request=request).exists()
    assert len(portal.submissions) == (0 if phase == "prepare" else 1)

    def forbidden_session(company_id):
        pytest.fail("Old deliveries cannot access SEFAZ after cancellation")

    for sibling in request.parts.all():
        assert (
            advance_part(
                sibling.pk,
                client_factory=forbidden_session,
                now=now + timedelta(hours=1),
                dispatch=False,
            ).status
            == "cancelled"
        )


def test_deletion_removes_downloaded_notes_files_and_preserves_audit(
    lifecycle_request, lifecycle_admin, tmp_path, settings
):
    settings.FISCAL_NOTES_ROOT = tmp_path / "notes"
    request = lifecycle_request
    part = request.parts.get(format="xml")
    portal = Portal(tmp_path, Period(part.start_date, part.end_date))
    now = timezone.now()
    advance_part(part.pk, client_factory=portal.open, now=now, dispatch=False)
    assert (
        advance_part(
            part.pk,
            client_factory=portal.open,
            now=now + timedelta(minutes=2),
            dispatch=False,
        ).status
        == "succeeded"
    )
    archive = part.archives.get()
    original = settings.FISCAL_NOTES_ROOT / archive.path
    member_paths = [
        settings.FISCAL_NOTES_ROOT / item.path for item in archive.members.all()
    ]
    cancel(request, lifecycle_admin)
    delete_cancelled_download_request(
        request.pk, actor_id=lifecycle_admin.pk, note="Limpeza da tela", dispatch=False
    )
    request.refresh_from_db()
    part.refresh_from_db()
    assert request.status == "cancelled"
    assert request.deleted_at is not None
    assert part.status == "succeeded"
    assert not part.archives.exists()
    assert not request.company.invoices.exists()
    from apps.fiscal.tasks import purge_download_files

    purge_download_files.run(str(request.pk))
    assert not original.exists()
    assert all(not path.exists() for path in member_paths)
    assert AuditLog.objects.filter(
        action="fiscal.download_deleted", target=f"download:{request.pk}"
    ).exists()
