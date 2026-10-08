import base64
import gzip
from pathlib import Path
from typing import Any

import pytest

from apps.fiscal.models import DistributionBatch, NsuControl
from apps.fiscal.services.distribution import (
    persist_distribution_response,
    reprocess_distribution_batch,
    request_distribution_batch_reprocessing,
)
from apps.fiscal.services.storage import FiscalStorage, FiscalStorageError
from apps.organizations.models import AccountingOffice, ClientCompany


ACCESS_KEY = "25010100000000000191550010000000011000000010"


class _FailFirstDocumentStorage(FiscalStorage):
    def __init__(self, root: Path) -> None:
        super().__init__(root=root)
        self.fail_document_write = True

    def write_document(self, **kwargs: Any) -> str:
        if self.fail_document_write:
            self.fail_document_write = False
            raise FiscalStorageError("simulated local storage failure")
        return super().write_document(**kwargs)


def _company() -> ClientCompany:
    office = AccountingOffice.objects.create(
        legal_name="Contabilidade Exemplo Ltda.",
        tax_identifier="00000000000191",
    )
    return ClientCompany.objects.create(
        office=office,
        legal_name="Cliente Exemplo Ltda.",
        tax_identifier="00000000000191",
    )


def _response_with_document() -> bytes:
    document = f"""<resNFe xmlns="http://www.portalfiscal.inf.br/nfe">
      <chNFe>{ACCESS_KEY}</chNFe><mod>55</mod>
    </resNFe>""".encode()
    encoded = base64.b64encode(gzip.compress(document)).decode("ascii")
    return f"""<retDistDFeInt xmlns="http://www.portalfiscal.inf.br/nfe" versao="1.01">
      <tpAmb>1</tpAmb><verAplic>TESTE</verAplic><cStat>138</cStat>
      <xMotivo>Documento localizado</xMotivo>
      <dhResp>2026-10-08T10:00:00-03:00</dhResp>
      <ultNSU>000000000000001</ultNSU><maxNSU>000000000000001</maxNSU>
      <loteDistDFeInt><docZip NSU="000000000000001" schema="resNFe_v1.01.xsd">
        {encoded}
      </docZip></loteDistDFeInt>
    </retDistDFeInt>""".encode()


@pytest.mark.django_db
def test_failed_local_processing_keeps_raw_batch_for_idempotent_reprocessing(
    tmp_path: Path,
) -> None:
    company = _company()
    control = NsuControl.objects.create(
        company=company,
        environment=NsuControl.Environment.PRODUCTION,
    )
    payload = _response_with_document()
    failing_storage = _FailFirstDocumentStorage(tmp_path)

    with pytest.raises(FiscalStorageError):
        persist_distribution_response(
            control_id=control.pk,
            raw_response=payload,
            storage=failing_storage,
        )

    batch = DistributionBatch.objects.get(company=company)
    control.refresh_from_db()
    assert batch.processing_status == DistributionBatch.ProcessingStatus.FAILED
    assert (tmp_path / batch.raw_response_path).read_bytes() == payload
    assert control.last_nsu == ""
    assert batch.items.count() == 0

    ignored = reprocess_distribution_batch(
        batch_id=batch.pk,
        storage=FiscalStorage(root=tmp_path),
    )
    first = request_distribution_batch_reprocessing(batch_id=batch.pk)
    repeated = request_distribution_batch_reprocessing(batch_id=batch.pk)
    processed = reprocess_distribution_batch(
        batch_id=batch.pk,
        storage=FiscalStorage(root=tmp_path),
    )

    batch.refresh_from_db()
    control.refresh_from_db()
    assert first.created is True
    assert repeated.created is False
    assert ignored.processing_status == DistributionBatch.ProcessingStatus.FAILED
    assert processed.pk == batch.pk
    assert batch.processing_status == DistributionBatch.ProcessingStatus.PROCESSED
    assert batch.processing_error == ""
    assert batch.items.count() == 1
    assert company.fiscal_documents.count() == 1
    assert control.last_nsu == "000000000000001"

    reprocessed_again = reprocess_distribution_batch(
        batch_id=batch.pk,
        storage=FiscalStorage(root=tmp_path),
    )
    assert reprocessed_again.pk == batch.pk
    assert batch.items.count() == 1
    assert company.fiscal_documents.count() == 1
