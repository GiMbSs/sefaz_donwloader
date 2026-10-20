import hashlib
import json

from apps.fiscal.atf.profiles import document_profile
from apps.fiscal.atf.types import DownloadFormat, Period


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
