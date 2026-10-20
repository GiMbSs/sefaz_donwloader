"""Document-specific ATF contracts; authentication and mailbox stay shared."""

from dataclasses import dataclass

from django.conf import settings

DOCUMENT_CHOICES = [("55", "NF-e"), ("65", "NFC-e")]


@dataclass(frozen=True)
class DocumentProfile:
    model: str
    label: str
    sender_code: str
    query_path: str
    component_id: str


PROFILES = {
    "55": DocumentProfile(
        "55",
        "NF-e",
        "FIS_1322",
        "/atf/fis/FISf_ConsultarNFeXml2.do",
        "FISf_ConsultarNFeXml2_cmpEmit",
    ),
    "65": DocumentProfile(
        "65",
        "NFC-e",
        "FIS_1484",
        "/atf/fis/FISf_ConsultaGenericaEmitenteNFCe.do",
        "FISf_ConsultaGenericaEmitenteNFCe_cmpEmit",
    ),
}


def document_profile(model: str) -> DocumentProfile:
    if model not in PROFILES:
        raise ValueError("Selecione NF-e ou NFC-e.")
    return PROFILES[model]


def result_wait_seconds(model: str) -> int:
    document_profile(model)
    name = (
        "ATF_NFCE_WAIT_TIMEOUT_SECONDS" if model == "65" else "ATF_WAIT_TIMEOUT_SECONDS"
    )
    return max(3600, int(getattr(settings, name, 604800 if model == "65" else 86400)))
