"""Fence physical cleanup against publishers, including changed CNPJ paths."""

from django.db import connection

# Shared by all fiscal publishers; cleanup takes this lock exclusively.
FISCAL_STORAGE_LOCK = 0x534546415A


def lock_fiscal_storage(*, cleanup: bool = False) -> None:
    if not connection.in_atomic_block:
        raise RuntimeError("Fiscal storage coordination requires a transaction.")
    if connection.vendor == "postgresql":
        function = (
            "pg_advisory_xact_lock" if cleanup else "pg_advisory_xact_lock_shared"
        )
        with connection.cursor() as cursor:
            cursor.execute(f"SELECT {function}(%s)", [FISCAL_STORAGE_LOCK])
