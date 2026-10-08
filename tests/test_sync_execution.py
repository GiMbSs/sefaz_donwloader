from datetime import time, timedelta

import pytest
from django.utils import timezone

from apps.certificates.models import DigitalCertificate
from apps.fiscal.models import NsuControl, SyncPolicy, SyncRequest
from apps.fiscal.services.execution import execute_sync_request
from apps.fiscal.services.sefaz import (
    SefazDistributionResult,
    SefazTransportError,
)
from apps.fiscal.services.storage import FiscalStorage
from apps.fiscal.services.sync import (
    enqueue_due_synchronizations,
    request_synchronization,
)
from apps.organizations.models import AccountingOffice, ClientCompany


def _company() -> ClientCompany:
    office = AccountingOffice.objects.create(
        legal_name="Contabilidade Exemplo Ltda.",
        tax_identifier="00000000000191",
    )
    company = ClientCompany.objects.create(
        office=office,
        legal_name="Cliente Exemplo Ltda.",
        tax_identifier="00000000000191",
    )
    SyncPolicy.objects.create(
        company=company,
        mode=SyncPolicy.Mode.HYBRID,
        scheduled_time=time(2, 0),
    )
    return company


def _certificate(company: ClientCompany, *, now) -> DigitalCertificate:
    return DigitalCertificate.objects.create(
        company=company,
        encrypted_path=f"certificates/{company.pk}/certificate.pfx.enc",
        encrypted_password_path=f"certificates/{company.pk}/password.enc",
        password_hash="not-a-recoverable-password",
        filename="empresa.pfx",
        content_sha256="a" * 64,
        certificate_fingerprint_sha256="b" * 64,
        serial_number=f"serial-{company.pk}",
        subject="CN=Empresa de Teste",
        issuer="CN=Autoridade de Teste",
        not_valid_before=now - timedelta(days=1),
        not_valid_after=now + timedelta(days=30),
    )


def _distribution_response(*, status_code: str = "137") -> bytes:
    return f"""<?xml version="1.0" encoding="utf-8"?>
    <retDistDFeInt xmlns="http://www.portalfiscal.inf.br/nfe" versao="1.01">
      <tpAmb>1</tpAmb><verAplic>TESTE</verAplic><cStat>{status_code}</cStat>
      <xMotivo>Sem novos documentos</xMotivo>
      <dhResp>2026-10-07T10:00:00-03:00</dhResp>
      <ultNSU>000000000000000</ultNSU><maxNSU>000000000000000</maxNSU>
    </retDistDFeInt>""".encode()


class _SuccessfulClient:
    def __init__(self, response: bytes) -> None:
        self.response = response
        self.calls: list[dict[str, object]] = []

    def request_dist_nsu(self, **kwargs: object) -> SefazDistributionResult:
        self.calls.append(kwargs)
        return SefazDistributionResult(
            endpoint="https://sefaz.example.test/distribution",
            soap_response=b"<soap-response />",
            distribution_response=self.response,
        )


class _FailingTransportClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def request_dist_nsu(self, **kwargs: object) -> SefazDistributionResult:
        self.calls.append(kwargs)
        raise SefazTransportError("network unavailable")


@pytest.mark.django_db
def test_worker_executes_once_archives_response_and_finishes_request(tmp_path):
    now = timezone.now()
    company = _company()
    _certificate(company, now=now)
    submission = request_synchronization(
        company_id=company.pk,
        environment=NsuControl.Environment.PRODUCTION,
        trigger=SyncRequest.Trigger.MANUAL,
        dispatch=False,
        now=now,
    )
    client = _SuccessfulClient(_distribution_response())

    result = execute_sync_request(
        submission.request.pk,
        client=client,  # type: ignore[arg-type]
        storage=FiscalStorage(root=tmp_path),
        now=now,
    )

    submission.request.refresh_from_db()
    policy = SyncPolicy.objects.get(company=company)
    control = NsuControl.objects.get(company=company)
    assert result == SyncRequest.Status.SUCCEEDED
    assert submission.request.status == SyncRequest.Status.SUCCEEDED
    assert submission.request.result_detail.startswith("SEFAZ respondeu cStat 137")
    assert policy.last_result == "137"
    assert policy.failure_count == 0
    assert control.last_status_code == "137"
    assert control.next_allowed_at is not None
    assert len(client.calls) == 1
    assert company.distribution_batches.count() == 1
    batch = company.distribution_batches.get()
    assert batch.sync_request_id == submission.request.pk
    assert (tmp_path / batch.raw_response_path).read_bytes() == _distribution_response()
    assert (tmp_path / batch.soap_response_path).read_bytes() == b"<soap-response />"
    SyncRequest.objects.filter(pk=submission.request.pk).update(
        status=SyncRequest.Status.RUNNING,
        finished_at=None,
    )
    assert (
        execute_sync_request(
            submission.request.pk,
            client=client,  # type: ignore[arg-type]
            storage=FiscalStorage(root=tmp_path),
            now=now,
        )
        == SyncRequest.Status.SUCCEEDED
    )
    submission.request.refresh_from_db()
    assert submission.request.status == SyncRequest.Status.SUCCEEDED
    assert len(client.calls) == 1


@pytest.mark.django_db
def test_waiting_request_is_only_released_after_the_persisted_hold_expires():
    now = timezone.now()
    company = _company()
    SyncPolicy.objects.filter(company=company).update(
        mode=SyncPolicy.Mode.MANUAL,
        scheduled_time=None,
    )
    control = NsuControl.objects.create(
        company=company,
        environment=NsuControl.Environment.PRODUCTION,
        next_allowed_at=now + timedelta(hours=1),
    )
    submission = request_synchronization(
        company_id=company.pk,
        environment=NsuControl.Environment.PRODUCTION,
        trigger=SyncRequest.Trigger.MANUAL,
        dispatch=False,
        now=now,
    )
    client = _SuccessfulClient(_distribution_response())

    result = execute_sync_request(
        submission.request.pk,
        client=client,  # type: ignore[arg-type]
        now=now,
    )
    submission.request.refresh_from_db()

    assert result == SyncRequest.Status.WAITING
    assert submission.request.status == SyncRequest.Status.WAITING
    assert client.calls == []
    assert (
        enqueue_due_synchronizations(
            now=control.next_allowed_at + timedelta(seconds=1)
        )
        == 1
    )
    submission.request.refresh_from_db()
    assert submission.request.status == SyncRequest.Status.QUEUED


@pytest.mark.django_db
def test_transport_failure_finishes_request_and_applies_conservative_hold():
    now = timezone.now()
    company = _company()
    _certificate(company, now=now)
    submission = request_synchronization(
        company_id=company.pk,
        environment=NsuControl.Environment.PRODUCTION,
        trigger=SyncRequest.Trigger.MANUAL,
        dispatch=False,
        now=now,
    )
    client = _FailingTransportClient()

    result = execute_sync_request(
        submission.request.pk,
        client=client,  # type: ignore[arg-type]
        now=now,
    )

    submission.request.refresh_from_db()
    control = NsuControl.objects.get(company=company)
    policy = SyncPolicy.objects.get(company=company)
    assert result == SyncRequest.Status.FAILED
    assert submission.request.status == SyncRequest.Status.FAILED
    assert "não pôde ser confirmada" in submission.request.result_detail
    assert control.next_allowed_at is not None
    assert control.next_allowed_at >= now + timedelta(minutes=59)
    assert policy.last_result == "failed"
    assert policy.failure_count == 1
    assert len(client.calls) == 1


@pytest.mark.django_db
def test_worker_does_not_contact_sefaz_without_an_active_certificate():
    now = timezone.now()
    company = _company()
    submission = request_synchronization(
        company_id=company.pk,
        environment=NsuControl.Environment.PRODUCTION,
        trigger=SyncRequest.Trigger.MANUAL,
        dispatch=False,
        now=now,
    )
    client = _SuccessfulClient(_distribution_response())

    result = execute_sync_request(
        submission.request.pk,
        client=client,  # type: ignore[arg-type]
        now=now,
    )

    submission.request.refresh_from_db()
    assert result == SyncRequest.Status.FAILED
    assert submission.request.status == SyncRequest.Status.FAILED
    assert "Não há certificado A1" in submission.request.result_detail
    assert client.calls == []
