import calendar
import hashlib
import json
from datetime import date, timedelta

from apps.fiscal.atf.profiles import document_profile
from apps.fiscal.atf.types import DownloadFormat, Period


def split_period(period: Period, document_model: str = "55") -> tuple[Period, ...]:
    document_profile(document_model)
    parts = []
    start = period.start
    while start <= period.end:
        end = (
            start
            if document_model == "65"
            else min(
                date(
                    start.year,
                    start.month,
                    calendar.monthrange(start.year, start.month)[1],
                ),
                period.end,
            )
        )
        parts.append(Period(start, end))
        if end == period.end:
            break
        start = end + timedelta(days=1)
    return tuple(parts)


def active_request_key(
    company_id: int,
    period: Period,
    formats: tuple[DownloadFormat, ...],
    document_model: str = "55",
) -> str:
    document_profile(document_model)
    if not formats or set(formats) - {"xml", "txt"}:
        raise ValueError("Selecione XML, TXT ou ambos.")
    value = [
        company_id,
        period.start.isoformat(),
        period.end.isoformat(),
        sorted(set(formats)),
    ]
    if document_model != "55":
        value.append(document_model)
    return hashlib.sha256(json.dumps(value).encode()).hexdigest()
