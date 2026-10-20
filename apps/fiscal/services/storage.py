"""Atomic private storage for SEFAZ responses and extracted XML files."""

from __future__ import annotations

import os
import tempfile
import uuid
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING

from django.conf import settings
from django.core.exceptions import ValidationError

from apps.fiscal.atf.profiles import document_profile
from apps.organizations.validators import (
    normalize_tax_identifier,
    validate_tax_identifier,
)

if TYPE_CHECKING:
    from apps.organizations.models import ClientCompany


class FiscalStorageError(Exception):
    pass


def download_storage_directory(
    company: ClientCompany,
    *,
    document_model: str,
    format: str,
    requested_on: date,
) -> Path:
    """Keep new fiscal files tenant-scoped using the original request date."""
    profile = document_profile(document_model)
    if format not in {"xml", "txt"}:
        raise FiscalStorageError("Unsupported fiscal storage format.")
    office_cnpj = normalize_tax_identifier(company.office.tax_identifier)
    company_cnpj = normalize_tax_identifier(company.tax_identifier)
    try:
        validate_tax_identifier(office_cnpj)
        validate_tax_identifier(company_cnpj)
    except ValidationError as error:
        raise FiscalStorageError("Invalid fiscal storage identity.") from error
    return (
        Path(office_cnpj)
        / company_cnpj
        / ("NFCe" if profile.model == "65" else "NFe")
        / format.upper()
        / requested_on.isoformat()
    )


class FiscalStorage:
    def __init__(self, root: Path | None = None) -> None:
        self.root = root or settings.FISCAL_NOTES_ROOT

    def _safe_target(self, relative_path: Path) -> Path:
        target = (self.root / relative_path).resolve()
        if self.root.resolve() not in target.parents:
            raise FiscalStorageError("Storage path escaped the notes root.")
        return target

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
