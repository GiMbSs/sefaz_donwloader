"""Read download names without accepting remote filesystem paths."""

import re
from email.message import Message
from email.utils import collapse_rfc2231_value


def safe_archive_filename(value: str | None) -> str | None:
    if (
        not value
        or value != value.strip()
        or not value.lower().endswith(".zip")
        or value.lower() == ".zip"
        or re.search(r'[<>:"/\\|?*\x00-\x1f\x7f]', value)
        or re.match(r"(?:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)", value, re.I)
    ):
        return None
    try:
        if len(value.encode("utf-8")) > 255:
            return None
    except UnicodeError:
        return None
    return value


def attachment_filename(header: str, fallback: str | None = None) -> str | None:
    message = Message()
    message["Content-Disposition"] = header
    parameters = message.get_params(header="content-disposition") or []
    # RFC 2231/5987 names take precedence over the ASCII compatibility name.
    values = [value for key, value in parameters if key.lower() == "filename"]
    values.sort(key=lambda value: not isinstance(value, tuple))
    for value in values:
        decoded = collapse_rfc2231_value(value) if isinstance(value, tuple) else value
        name = safe_archive_filename(decoded)
        if name:
            return name
    return safe_archive_filename(fallback)
