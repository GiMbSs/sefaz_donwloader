"""Atomic private storage for SEFAZ responses and extracted XML files."""

from __future__ import annotations

import os
import tempfile
import uuid
from pathlib import Path
from typing import TYPE_CHECKING

from django.conf import settings

from apps.organizations.storage import company_storage_directory

if TYPE_CHECKING:
    from apps.organizations.models import ClientCompany


class FiscalStorageError(Exception):
    pass


class FiscalStorage:
    def __init__(self, root: Path | None = None) -> None:
        self.root = root or settings.FISCAL_NOTES_ROOT

    def _safe_target(self, relative_path: Path) -> Path:
        target = (self.root / relative_path).resolve()
        if self.root.resolve() not in target.parents:
            raise FiscalStorageError("Storage path escaped the notes root.")
        return target

    def write_response(
        self,
        company_id: int | None,
        response: bytes,
        *,
        company: ClientCompany | None = None,
        category: str = "distribution",
    ) -> str:
        if category not in {"distribution", "soap"}:
            raise FiscalStorageError("Response storage category is not supported.")
        company_root = self._company_directory(company=company, company_id=company_id)
        directory = "lotes" if category == "distribution" else "soap"
        relative_path = company_root / directory / f"{category}-{uuid.uuid4()}.xml"
        self._write(relative_path, response)
        return str(relative_path)

    def write_document(
        self,
        *,
        company_id: int | None,
        company: ClientCompany | None = None,
        model: str,
        access_key: str,
        kind: str,
        discriminator: str = "",
        issued_year: int = 0,
        issued_month: int = 0,
        payload: bytes,
    ) -> str:
        if (
            not access_key.isascii()
            or not access_key.isalnum()
            or len(access_key) != 44
        ):
            raise FiscalStorageError(
                "Access key must have 44 uppercase alphanumeric characters."
            )
        if not model.isdecimal() or len(model) != 2:
            raise FiscalStorageError("Document model must have two digits.")
        if not 1 <= issued_month <= 12:
            issued_year, issued_month = 0, 0
        if kind == "complete":
            filename = f"{access_key}.xml"
        elif kind == "summary":
            filename = f"{access_key}.summary.xml"
        elif kind in {"event", "unknown"} and discriminator:
            filename = f"{access_key}.{kind}.{discriminator}.xml"
        else:
            raise FiscalStorageError(
                "Document kind requires a safe filename discriminator."
            )
        relative_path = (
            self._company_directory(company=company, company_id=company_id)
            / "xmls"
            / f"{issued_year:04d}"
            / f"{issued_month:02d}"
            / model
            / filename
        )
        self._write(relative_path, payload)
        return str(relative_path)

    def _company_directory(
        self,
        *,
        company: ClientCompany | None,
        company_id: int | None,
    ) -> Path:
        if company is not None:
            return company_storage_directory(company)
        if company_id is None:
            raise FiscalStorageError("A company is required for fiscal storage.")
        return Path(str(company_id))

    def delete(self, relative_path: str) -> None:
        """Delete a file created during a failed database transaction."""
        target = self._safe_target(Path(relative_path))
        try:
            target.unlink()
        except FileNotFoundError:
            return
        except OSError as error:
            raise FiscalStorageError(
                "Unable to remove incomplete fiscal storage data."
            ) from error

    def path_for_read(self, relative_path: str) -> Path:
        target = self._safe_target(Path(relative_path))
        if not target.is_file():
            raise FiscalStorageError(
                "Fiscal XML is not available in the configured storage."
            )
        return target

    def probe_writable(self) -> None:
        """Verify an atomic write/delete cycle without retaining fiscal data."""
        relative_path = Path(f".sefaz-preflight-{uuid.uuid4()}")
        try:
            self._write(relative_path, b"sefaz-downloader storage preflight\n")
            self.delete(str(relative_path))
        except OSError as error:
            raise FiscalStorageError(
                "Fiscal storage did not complete an atomic write probe."
            ) from error

    def _write(self, relative_path: Path, payload: bytes) -> None:
        target = self._safe_target(relative_path)
        target.parent.mkdir(mode=0o750, parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=".download-",
            dir=target.parent,
        )
        try:
            with os.fdopen(descriptor, "wb") as temporary:
                os.fchmod(temporary.fileno(), 0o640)
                temporary.write(payload)
                temporary.flush()
                os.fsync(temporary.fileno())
            os.replace(temporary_name, target)
            os.chmod(target, 0o640)
        except OSError:
            try:
                os.unlink(temporary_name)
            except FileNotFoundError:
                pass
            raise
