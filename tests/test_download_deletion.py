from datetime import timedelta

import pytest
from django.utils import timezone

from apps.fiscal.atf.types import Period
from apps.fiscal.models import (
    ArchiveMember,
    DownloadArchive,
    DownloadPart,
    DownloadRequest,
)
from apps.fiscal.services.download_lifecycle import (
    cancel_download_request,
    delete_cancelled_download_request,
)
from apps.fiscal.services.downloads import advance_part
from tests.test_download_execution import Portal
from tests.test_nfce_downloads import NfcePortal


@pytest.fixture(params=["55", "65"])
def deletion_case(lifecycle_request, lifecycle_admin, settings, tmp_path, request):
    model = request.param
    settings.FISCAL_NOTES_ROOT = tmp_path / "notes"
    request = lifecycle_request
    request.document_model = model
    request.save()
    part = request.parts.get(format="xml")
    portal = (Portal if model == "55" else NfcePortal)(
        tmp_path, Period(part.start_date, part.end_date)
    )
    portal.ready = True
    now = timezone.now()
    advance_part(part.pk, client_factory=portal.open, now=now, dispatch=False)
    advance_part(
        part.pk,
        client_factory=portal.open,
        now=now + timedelta(minutes=2),
        dispatch=False,
    )
    archive = part.archives.first()
    cancel_download_request(
        request.pk,
        actor_id=lifecycle_admin.pk,
        note="Encerrar",
        acknowledge_remote_uncertainty=True,
    )
    return request, archive


def other_reference(request, archive, *, copy_member=True):
    other = DownloadRequest.objects.create(
        company=request.company,
        start_date=request.start_date,
        end_date=request.end_date,
        active_key="other-physical-reference",
        formats=["xml"],
    )
    part = DownloadPart.objects.create(
        request=other,
        start_date=request.start_date,
        end_date=request.end_date,
        format="xml",
    )
    other_archive = DownloadArchive.objects.create(
        part=part,
        remote_account_key="a" * 64,
        message_id="another-message",
        attachment_index=0,
        path=archive.path,
        filename=archive.filename,
        sha256=archive.sha256,
        byte_count=archive.byte_count,
    )
    if copy_member:
        original = archive.members.first()
        ArchiveMember.objects.create(
            archive=other_archive,
            name=original.name,
            kind=original.kind,
            path=original.path,
            invoice_version=original.invoice_version,
            sha256=original.sha256,
            byte_count=original.byte_count,
        )
    return other_archive


def test_delete_preserves_shared_invoice_and_files(
    deletion_case, lifecycle_admin, settings
):
    from apps.fiscal.services.download_deletion import purge_request_files

    request, archive = deletion_case
    shared = other_reference(request, archive)
    member = shared.members.get()
    delete_cancelled_download_request(
        request.pk,
        actor_id=lifecycle_admin.pk,
        note="Remover exclusivos",
        dispatch=False,
    )
    purge_request_files(request.pk)
    assert not DownloadArchive.objects.filter(pk=archive.pk).exists()
    assert DownloadArchive.objects.filter(pk=shared.pk).exists()
    assert (settings.FISCAL_NOTES_ROOT / shared.path).is_file()
    assert (settings.FISCAL_NOTES_ROOT / member.path).is_file()
    assert request.company.invoices.get().versions.get().pk == member.invoice_version_id


def test_file_cleanup_is_retryable_after_storage_failure(
    deletion_case, lifecycle_admin, settings, monkeypatch
):
    from apps.fiscal.models import DownloadFileDeletion
    from apps.fiscal.services.download_deletion import purge_request_files
    from apps.fiscal.services.storage import FiscalStorage, FiscalStorageError

    request, archive = deletion_case
    delete_cancelled_download_request(
        request.pk, actor_id=lifecycle_admin.pk, note="Excluir", dispatch=False
    )
    original_delete = FiscalStorage.delete
    with monkeypatch.context() as patch:

        def fail(*args, **kwargs):
            raise FiscalStorageError("Synthetic unavailable filesystem")

        patch.setattr(FiscalStorage, "delete", fail)
        purge_request_files(request.pk)
    assert DownloadFileDeletion.objects.filter(
        request=request, completed_at__isnull=True
    ).exists()
    assert (settings.FISCAL_NOTES_ROOT / archive.path).is_file()
    assert FiscalStorage.delete == original_delete
    purge_request_files(request.pk)
    assert not DownloadFileDeletion.objects.filter(
        request=request, completed_at__isnull=True
    ).exists()
    assert not (settings.FISCAL_NOTES_ROOT / archive.path).exists()


def test_cleanup_rechecks_new_file_references_before_unlinking(
    deletion_case, lifecycle_admin, settings
):
    from apps.fiscal.services.download_deletion import purge_request_files

    request, archive = deletion_case
    delete_cancelled_download_request(
        request.pk, actor_id=lifecycle_admin.pk, note="Excluir", dispatch=False
    )
    # Another request reuses the existing ZIP after deletion was queued.
    other_reference(request, archive, copy_member=False)
    purge_request_files(request.pk)
    assert (settings.FISCAL_NOTES_ROOT / archive.path).is_file()


def test_periodic_cleanup_prioritizes_requests_with_fewer_attempts(
    lifecycle_request, monkeypatch
):
    from apps.fiscal.models import DownloadFileDeletion
    from apps.fiscal.tasks import purge_download_files

    base = lifecycle_request
    requests = DownloadRequest.objects.bulk_create(
        [
            DownloadRequest(
                company=base.company,
                start_date=base.start_date,
                end_date=base.end_date,
                active_key=f"retry-fairness-{index}",
                status="cancelled",
                deleted_at=timezone.now(),
            )
            for index in range(101)
        ]
    )
    DownloadFileDeletion.objects.bulk_create(
        [
            DownloadFileDeletion(
                request=item,
                path=f"file-{index}.zip",
                attempts=5 if index < 100 else 0,
                outcome="storage_unavailable" if index < 100 else "",
            )
            for index, item in enumerate(requests)
        ]
    )
    visited = []
    monkeypatch.setattr(
        "apps.fiscal.services.download_deletion.purge_request_files",
        lambda request_id: visited.append(request_id) or 0,
    )
    monkeypatch.setattr(
        "apps.fiscal.services.download_deletion.dispatch_file_deletion",
        lambda *args, **kwargs: None,
    )
    purge_download_files.run()
    assert visited[0] == requests[-1].pk
    assert len(visited) == 100


def test_old_revalidation_job_does_not_recreate_deleted_files(
    deletion_case, lifecycle_admin, settings
):
    from apps.fiscal.services.download_deletion import purge_request_files
    from apps.fiscal.tasks import revalidate_download_archive

    request, archive = deletion_case
    delete_cancelled_download_request(
        request.pk, actor_id=lifecycle_admin.pk, note="Excluir", dispatch=False
    )
    purge_request_files(request.pk)
    assert revalidate_download_archive.run(str(archive.pk)) == "deleted"
    assert not (settings.FISCAL_NOTES_ROOT / archive.path).exists()
