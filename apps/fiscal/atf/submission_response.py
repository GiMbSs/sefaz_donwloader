"""Interpret explicit SEFAZ confirmation or rejection, never infer success."""

import re

from .errors import AtfCaptchaRequired, AtfSubmissionUncertain
from .forms import portal_document, visible_text
from .types import SubmissionReceipt


def submission_receipt(content: bytes) -> SubmissionReceipt:
    tree = portal_document(content)
    source = "\n".join(tree.xpath("//script[not(@src)]/text()"))
    if "SEGf_EmitirMensagem" in source and re.search(
        r"\b(?:cod|codigo)\s*=\s*['\"]3291['\"]", source
    ):
        raise AtfCaptchaRequired()
    text = visible_text(tree).lower()
    if "resultado será enviado para sua caixa de mensagens" not in text:
        raise AtfSubmissionUncertain()
    return SubmissionReceipt(True)
