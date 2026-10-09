"""Stable, tenant-scoped directory names for client-owned files."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from .validators import normalize_tax_identifier

if TYPE_CHECKING:
    from .models import ClientCompany


def company_storage_directory(company: ClientCompany) -> Path:
    """Return the logical root shared by a company's private artifacts.

    The accounting-office segment prevents two tenants that happen to register
    the same CNPJ in one installation from sharing files.  The company segment
    intentionally follows the ``empresa_<cnpj>`` convention requested for the
    workstation folders and remains stable when the legal name is edited.
    """
    office_cnpj = normalize_tax_identifier(company.office.tax_identifier)
    company_cnpj = normalize_tax_identifier(company.tax_identifier)
    return (
        Path("escritorios")
        / f"escritorio_{office_cnpj}"
        / f"empresa_{company_cnpj}"
    )
