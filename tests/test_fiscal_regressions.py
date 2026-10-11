from datetime import timedelta

import pytest
from django.utils import timezone

from apps.accounts.models import User
from apps.fiscal.models import DistributionBatch, NsuControl, SyncPolicy, SyncRequest
from apps.fiscal.services.distribution import persist_distribution_response
from apps.fiscal.services.execution import _claim_sync_request
from apps.fiscal.services.recovery import (
    SynchronizationRecoveryError,
    recover_interrupted_request,
)
from apps.fiscal.services.storage import FiscalStorage
from apps.fiscal.services.sync import _is_due, request_synchronization
from apps.organizations.models import ClientCompany, OfficeMembership
from tests.test_distribution_reprocessing import _company, _response_with_document
from tests.test_sync_execution import _certificate


@pytest.mark.django_db
def test_duplicate_document_keeps_previously_archived_xml(tmp_path):
    company = _company()
    control = NsuControl.objects.create(company=company, environment="production")
    raw = _response_with_document()
    storage = FiscalStorage(root=tmp_path)
    persist_distribution_response(
        control_id=control.pk, raw_response=raw, storage=storage
    )
    document = company.fiscal_documents.get()
    target = tmp_path / document.xml_path
    original = target.read_bytes()
    second = raw.replace(b"10:00:00", b"10:01:00")
    batch = persist_distribution_response(
        control_id=control.pk, raw_response=second, storage=storage
    )
    assert target.read_bytes() == original
    document.refresh_from_db()
    assert document.xml_path == str(target.relative_to(tmp_path))
    assert batch.items.get().processing_status == "duplicate"


@pytest.mark.django_db
@pytest.mark.parametrize("change", ["inactive", "archived", "policy", "environment"])
def test_worker_revalidates_queued_request(change):
    now = timezone.now()
    company = _company()
    company.fiscal_environment = "production"
    company.save()
    SyncPolicy.objects.create(company=company, mode="manual")
    _certificate(company, now=now)
    submission = request_synchronization(
        company_id=company.pk,
        environment="production",
        trigger="manual",
        dispatch=False,
    )
    if change == "policy":
        SyncPolicy.objects.filter(company=company).update(is_active=False)
    elif change == "environment":
        ClientCompany.objects.filter(pk=company.pk).update(
            fiscal_environment="homologation"
        )
    else:
        ClientCompany.objects.filter(pk=company.pk).update(status=change)
    assert (
        _claim_sync_request(sync_request_id=submission.request.pk, now=now) == "failed"
    )
    submission.request.refresh_from_db()
    assert "não foi enviada" in submission.request.result_detail


@pytest.mark.django_db
def test_same_key_in_different_environments_has_independent_files(tmp_path):
    company = _company()
    storage = FiscalStorage(root=tmp_path)
    raw = _response_with_document()
    for environment, code in [("production", b"1"), ("homologation", b"2")]:
        control = NsuControl.objects.create(company=company, environment=environment)
        persist_distribution_response(
            control_id=control.pk,
            raw_response=raw.replace(b"<tpAmb>1", b"<tpAmb>" + code),
            storage=storage,
        )
    documents = list(company.fiscal_documents.order_by("environment"))
    assert len(documents) == 2
    assert documents[0].xml_path != documents[1].xml_path
    for document in documents:
        assert document.environment in document.xml_path.split("/")
        assert storage.path_for_read(document.xml_path).is_file()


@pytest.mark.django_db
def test_failed_replacement_preserves_previously_archived_file(tmp_path, monkeypatch):
    company = _company()
    control = NsuControl.objects.create(company=company, environment="production")
    raw = _response_with_document()
    storage = FiscalStorage(root=tmp_path)
    persist_distribution_response(
        control_id=control.pk, raw_response=raw, storage=storage
    )
    original = company.fiscal_documents.get()
    original_bytes = storage.path_for_read(original.xml_path).read_bytes()
    from apps.fiscal.services import distribution

    def fail(*args):
        raise RuntimeError("Simulated failure after document write")

    monkeypatch.setattr(distribution, "_advance_control", fail)
    changed = raw.replace(b"10:00:00", b"10:01:00")
    # A new XML representation causes a replacement under the same access key.
    import base64
    import gzip

    old = (
        raw.partition(b'schema="resNFe_v1.01.xsd">')[2]
        .partition(b"</docZip>")[0]
        .strip()
    )
    new = base64.b64encode(
        gzip.compress(original_bytes.replace(b"</resNFe>", b" </resNFe>"))
    )
    changed = changed.replace(old, new)
    with pytest.raises(RuntimeError):
        persist_distribution_response(
            control_id=control.pk, raw_response=changed, storage=storage
        )
    original.refresh_from_db()
    assert storage.path_for_read(original.xml_path).read_bytes() == original_bytes


@pytest.mark.django_db
def test_recovery_preserves_cursor_and_enforces_new_hold():
    now = timezone.now()
    company = _company()
    actor = User.objects.create_user(email="recovery@example.test", password="test")
    OfficeMembership.objects.create(office=company.office, user=actor, role="admin")
    control = NsuControl.objects.create(
        company=company, environment="production", last_nsu="000000000000042"
    )
    request = SyncRequest.objects.create(
        company=company,
        environment="production",
        trigger="manual",
        status="running",
        started_at=now - timedelta(hours=2),
    )
    with pytest.raises(SynchronizationRecoveryError):
        recover_interrupted_request(
            request_id=request.pk, actor=actor, reason="Worker interrompido", now=now
        )
    recovered = recover_interrupted_request(
        request_id=request.pk,
        actor=actor,
        reason="Worker interrompido",
        worker_stopped=True,
        now=now,
    )
    control.refresh_from_db()
    assert recovered.status == "failed"
    assert control.last_nsu == "000000000000042"
    assert control.next_allowed_at >= now + timedelta(hours=1)


@pytest.mark.django_db
def test_daily_policy_respects_selected_weekdays():
    now = timezone.now().astimezone(timezone.get_default_timezone())
    company = _company()
    policy = SyncPolicy.objects.create(
        company=company,
        mode="automatic",
        scheduled_time=now.time().replace(tzinfo=None),
        weekdays=[(now.weekday() + 1) % 7],
    )
    assert not _is_due(policy, now)
    policy.weekdays = [now.weekday()]
    assert _is_due(policy, now)


@pytest.mark.django_db
def test_recovery_does_not_finish_recent_or_unauthorized_requests():
    now = timezone.now()
    company = _company()
    actor = User.objects.create_user(
        email="operator-recovery@example.test", password="test"
    )
    OfficeMembership.objects.create(office=company.office, user=actor, role="operator")
    NsuControl.objects.create(company=company, environment="production")
    request = SyncRequest.objects.create(
        company=company,
        environment="production",
        trigger="manual",
        status="running",
        started_at=now - timedelta(hours=2),
    )
    with pytest.raises(SynchronizationRecoveryError, match="autorização"):
        recover_interrupted_request(
            request_id=request.pk,
            actor=actor,
            reason="Revisão",
            worker_stopped=True,
            now=now,
        )
    OfficeMembership.objects.filter(user=actor).update(role="admin")
    request.started_at = now
    request.save(update_fields=("started_at",))
    with pytest.raises(SynchronizationRecoveryError, match="uma hora"):
        recover_interrupted_request(
            request_id=request.pk,
            actor=actor,
            reason="Revisão",
            worker_stopped=True,
            now=now,
        )
    request.refresh_from_db()
    assert request.status == "running"


@pytest.mark.django_db
def test_recovery_finishes_from_already_processed_batch_without_changing_cursor():
    now = timezone.now()
    company = _company()
    actor = User.objects.create_superuser(
        email="processed-recovery@example.test", password="test"
    )
    control = NsuControl.objects.create(
        company=company, environment="production", last_nsu="000000000000042"
    )
    request = SyncRequest.objects.create(
        company=company,
        environment="production",
        trigger="manual",
        status="running",
        started_at=now - timedelta(hours=2),
    )
    DistributionBatch.objects.create(
        company=company,
        nsu_control=control,
        sync_request=request,
        response_sha256="b" * 64,
        raw_response_path="legacy/batch.xml",
        status_code="138",
        processing_status="processed",
        processed_at=now,
    )
    recovered = recover_interrupted_request(
        request_id=request.pk,
        actor=actor,
        reason="Lote já processado",
        worker_stopped=True,
        now=now,
    )
    assert recovered.status == "succeeded"
    control.refresh_from_db()
    assert control.last_nsu == "000000000000042"
