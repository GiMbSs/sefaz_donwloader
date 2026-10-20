import re
from datetime import datetime

from .errors import AtfPortalChanged
from .forms import portal_document, visible_text
from .profiles import PROFILES
from .types import AttachmentRef, MessagePage, MessageRef, ParsedMessage, Period


def parse_message_page(content: bytes, parent_id: str | None = None) -> MessagePage:
    tree = portal_document(content)
    if not tree.xpath('//form[@name="frmMensagens"]'):
        raise AtfPortalChanged()
    items = {}
    for row in tree.xpath("//tr"):
        handlers = row.xpath(".//@href | .//@onclick")
        match = next(
            (
                m
                for h in handlers
                if (m := re.search(r"abrirFilhas\(['\"](\d+)['\"],\s*(\d+)\)", h))
            ),
            None,
        )
        if not match:
            continue
        text = " ".join(" ".join(row.itertext()).split())
        sender = re.search(r"\bFIS_\d+\b", text)
        sent = re.search(r"\d{2}/\d{2}/\d{4}\s+\d{2}:\d{2}:\d{2}", text)
        items[match[1]] = MessageRef(
            match[1],
            parent_id,
            sender[0] if sender else "",
            sent[0] if sent else "",
            bool(row.xpath('.//img[@alt="Anexo" or contains(@src,"clips.")]')),
            int(match[2]),
        )
    next_links = tree.xpath('//a[@rel="next" and not(@aria-disabled="true")]/@href')
    if not next_links:
        next_links = tree.xpath(
            '//a[contains(translate(normalize-space(.),"PRÓXIMA","próxima"),'
            '"próxima") and not(@aria-disabled="true")]/@href'
        )
    next_page = next_links[0] if next_links else None
    if next_page and next_page.startswith("javascript:"):
        raise AtfPortalChanged("atf_pagination_contract_unknown")
    return MessagePage(tuple(items.values()), next_page)


def parse_message(content: bytes, message_id: str, parent_id: str) -> ParsedMessage:
    tree = portal_document(content)
    text = visible_text(tree)
    codes = {
        code
        for code in re.findall(r"\bFIS_\d+\b", text)
        if code in {profile.sender_code for profile in PROFILES.values()}
    }
    if len(codes) != 1:
        raise AtfPortalChanged("atf_unrelated_message")
    sender_code = codes.pop()
    match = re.search(
        r"Per[ií]odo solicitado:\s*(\d{2}/\d{2}/\d{4})\s+a\s+(\d{2}/\d{2}/\d{4})",
        text,
        re.I,
    )
    period = None
    if match:
        try:
            period = Period(
                *(
                    datetime.strptime(value, "%d/%m/%Y").date()
                    for value in match.groups()
                )
            )
        except ValueError as error:
            raise AtfPortalChanged() from error
    attachments = {}
    for handler in tree.xpath("//@href | //@onclick"):
        index = re.search(r"mostrarArquivo\(\s*(\d+)\s*\)", handler)
        if index:
            attachments[int(index[1])] = AttachmentRef(message_id, int(index[1]))
    lower = text.lower()
    if attachments:
        outcome = "success"
    elif any(
        marker in lower
        for marker in [
            "nenhuma nf-e encontrada",
            "nenhuma nfc-e encontrada",
            "não foram encontradas notas fiscais",
        ]
    ):
        outcome = "empty"
    elif any(
        marker in lower for marker in ["tarefa executada com erro", "falha na execução"]
    ):
        outcome = "remote_failed"
    else:
        outcome = "pending"
    processing = any(
        marker in lower
        for marker in (
            "em processamento",
            "em execução",
            "aguarde",
            "será processad",
            "aguardando processamento",
        )
    )
    ref = MessageRef(message_id, parent_id, sender_code, "", bool(attachments))
    return ParsedMessage(
        ref,
        period,
        tuple(attachments.values()),
        outcome,
        {"processing": "true"} if processing and not attachments else {},
    )
