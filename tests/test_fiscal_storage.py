import pytest

from apps.fiscal.services.storage import FiscalStorage, FiscalStorageError
from apps.organizations.models import AccountingOffice, ClientCompany


ACCESS_KEY = "25010100000000000191550010000000011000000010"


def test_distinguishes_complete_summary_and_event_files(tmp_path):
    storage = FiscalStorage(root=tmp_path)

    complete = storage.write_document(
        company_id=10,
        model="55",
        access_key=ACCESS_KEY,
        kind="complete",
        payload=b"complete",
    )
    summary = storage.write_document(
        company_id=10,
        model="55",
        access_key=ACCESS_KEY,
        kind="summary",
        payload=b"summary",
    )
    event = storage.write_document(
        company_id=10,
        model="55",
        access_key=ACCESS_KEY,
        kind="event",
        discriminator="a1b2c3d4",
        payload=b"event",
    )

    assert (tmp_path / complete).read_bytes() == b"complete"
    assert (tmp_path / summary).read_bytes() == b"summary"
    assert (tmp_path / event).read_bytes() == b"event"


def test_rejects_filename_without_kind_discriminator(tmp_path):
    storage = FiscalStorage(root=tmp_path)

    with pytest.raises(FiscalStorageError):
        storage.write_document(
            company_id=10,
            model="55",
            access_key=ACCESS_KEY,
            kind="event",
            payload=b"event",
        )


def test_write_probe_does_not_retain_a_file(tmp_path):
    storage = FiscalStorage(root=tmp_path)

    storage.probe_writable()

    assert list(tmp_path.iterdir()) == []


@pytest.mark.django_db
def test_company_storage_uses_tenant_scoped_empresa_cnpj_directories(tmp_path):
    office = AccountingOffice.objects.create(
        legal_name="Contabilidade Exemplo",
        tax_identifier="00000000000191",
    )
    company = ClientCompany.objects.create(
        office=office,
        legal_name="Cliente Exemplo",
        tax_identifier="00000000E08G12",
    )
    storage = FiscalStorage(root=tmp_path)

    document_path = storage.write_document(
        company_id=company.pk,
        company=company,
        model="55",
        access_key=ACCESS_KEY,
        kind="complete",
        payload=b"complete",
    )
    batch_path = storage.write_response(
        company.pk,
        b"response",
        company=company,
    )

    root = (
        "escritorios/escritorio_00000000000191/"
        "empresa_00000000E08G12/"
    )
    assert document_path.startswith(f"{root}xmls/")
    assert batch_path.startswith(f"{root}lotes/")
