import pytest

from apps.fiscal.services.storage import FiscalStorage, FiscalStorageError


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
