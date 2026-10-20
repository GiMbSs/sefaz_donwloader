from pathlib import Path

import pytest

from apps.fiscal.services.storage import FiscalStorage, FiscalStorageError


def test_storage_rejects_paths_outside_notes_root(tmp_path):
    storage = FiscalStorage(root=tmp_path)
    with pytest.raises(FiscalStorageError):
        storage._write(Path("../escaped.xml"), b"private")


def test_write_probe_does_not_retain_a_file(tmp_path):
    storage = FiscalStorage(root=tmp_path)
    storage.probe_writable()
    assert list(tmp_path.iterdir()) == []


def test_atomic_storage_preserves_previous_file_on_failed_replace(
    tmp_path, monkeypatch
):
    storage = FiscalStorage(root=tmp_path)
    storage._write(Path("note.xml"), b"original")

    def fail(*args, **kwargs):
        raise OSError("simulated disk failure")

    monkeypatch.setattr("apps.fiscal.services.storage.os.replace", fail)
    with pytest.raises(OSError):
        storage._write(Path("note.xml"), b"replacement")
    assert (tmp_path / "note.xml").read_bytes() == b"original"
    assert list(tmp_path.iterdir()) == [tmp_path / "note.xml"]
