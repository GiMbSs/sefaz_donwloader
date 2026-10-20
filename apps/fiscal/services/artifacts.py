"""Validate original ZIPs before publication; never extract untrusted paths."""

import csv
import hashlib
import io
import lzma
import os
import re
import shutil
import stat
import tempfile
import unicodedata
import zipfile
import zlib
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

from django.conf import settings
from django.db import transaction
from lxml import etree

from apps.fiscal.atf.errors import AtfArtifactError, AtfIdentityMismatch
from apps.fiscal.atf.profiles import document_profile
from apps.fiscal.models import DownloadArchive, DownloadPart
from apps.organizations.models import ClientCompany
from apps.organizations.storage import company_storage_directory
from apps.organizations.validators import normalize_tax_identifier

from .schemas import NFE_NAMESPACE, FiscalSchemaError, parse_fiscal_xml
from .storage import FiscalStorage


@dataclass(frozen=True)
class ValidatedMember:
    name: str
    kind: str
    sha256: str
    byte_count: int
    metadata: dict[str, str]


@dataclass(frozen=True)
class ArchiveValidation:
    members: tuple[ValidatedMember, ...]
    warnings: tuple[str, ...]
    archive_sha256: str


def _limit(name: Any, default: Any) -> int:
    value = int(getattr(settings, name, default))
    if value <= 0:
        raise AtfArtifactError("atf_invalid_size_limit")
    return value


def _member_name(name: Any) -> str:
    normalized = unicodedata.normalize("NFC", name.replace("\\", "/"))
    path = PurePosixPath(normalized)
    if (
        not normalized
        or path.is_absolute()
        or PureWindowsPath(name).drive
        or any(part in {"..", "."} for part in normalized.split("/"))
        or "\x00" in normalized
        or len(normalized) > 1024
    ):
        raise AtfArtifactError("atf_unsafe_zip_path")
    return str(path)


def _xml_child(parent: Any, name: str) -> Any:
    nodes = [
        child
        for child in parent
        if isinstance(child.tag, str) and etree.QName(child).localname == name
    ]
    if len(nodes) != 1:
        raise AtfArtifactError("atf_invoice_structure")
    if etree.QName(nodes[0]).namespace not in {NFE_NAMESPACE, None}:
        raise AtfArtifactError("atf_xml_namespace_invalid")
    return nodes[0]


def _xml_issue_date(node: Any, qualified: bool) -> date:
    prefix = "n:" if qualified else ""
    ns = {"n": NFE_NAMESPACE}
    timestamp = node.findtext(f"{prefix}ide/{prefix}dhEmi", namespaces=ns)
    try:
        if timestamp is not None:
            if "T" not in timestamp:
                raise ValueError("Timestamp missing time separator")
            return datetime.fromisoformat(timestamp.strip()).date()
        return date.fromisoformat(
            (node.findtext(f"{prefix}ide/{prefix}dEmi", namespaces=ns) or "").strip()
        )
    except ValueError:
        raise AtfArtifactError("atf_xml_date_invalid") from None


def _xml_metadata(
    data: Any, expected_cnpj: Any, period: Any, document_model: str
) -> Any:
    try:
        root = parse_fiscal_xml(data)
        name = etree.QName(root).localname
        ns = {"n": NFE_NAMESPACE}
        if name not in {"nfeProc", "NFe", "procEventoNFe"}:
            raise AtfArtifactError("atf_unsupported_xml")
        payload = (
            root
            if name == "NFe"
            else _xml_child(root, "NFe" if name == "nfeProc" else "evento")
        )
        qualified = etree.QName(payload).namespace == NFE_NAMESPACE

        def path(value: str) -> str:
            return value if qualified else value.replace("n:", "")

        namespace_status = (
            "standard"
            if qualified and etree.QName(root).namespace == NFE_NAMESPACE
            else "unqualified_wrapper"
            if qualified
            else "unqualified_document"
        )
        if name in {"nfeProc", "NFe"}:
            node = _xml_child(payload, "infNFe")
            if (etree.QName(node).namespace == NFE_NAMESPACE) != qualified:
                raise AtfArtifactError("atf_xml_namespace_invalid")
            identifier = node.get("Id", "")
            if not re.fullmatch(r"NFe[0-9A-Z]{44}", identifier):
                raise AtfArtifactError("atf_xml_key_invalid")
            key = identifier[3:]
            cnpj = node.findtext(path("n:emit/n:CNPJ"), namespaces=ns)
            model = node.findtext(path("n:ide/n:mod"), namespaces=ns)
            environment = node.findtext(path("n:ide/n:tpAmb"), namespaces=ns)
            if cnpj != expected_cnpj:
                raise AtfIdentityMismatch("atf_xml_issuer_mismatch")
            if key[6:20] != expected_cnpj:
                raise AtfIdentityMismatch("atf_xml_key_issuer_mismatch")
            if model != document_model:
                raise AtfIdentityMismatch("atf_xml_model_mismatch")
            if key[20:22] != document_model:
                raise AtfIdentityMismatch("atf_xml_key_model_mismatch")
            if environment != "1":
                raise AtfArtifactError("atf_invoice_scope")
            issued = _xml_issue_date(node, qualified)
            if not period.start <= issued <= period.end:
                raise AtfArtifactError("atf_invoice_outside_period")
            protocols = (
                [
                    child
                    for child in root
                    if isinstance(child.tag, str)
                    and etree.QName(child).localname == "protNFe"
                ]
                if name == "nfeProc"
                else []
            )
            if len(protocols) > 1:
                raise AtfArtifactError("atf_invoice_structure")
            if protocols:
                protocol = protocols[0]
                if etree.QName(protocol).namespace not in {NFE_NAMESPACE, None}:
                    raise AtfArtifactError("atf_xml_namespace_invalid")
                protocol_path = (
                    "n:infProt/n:chNFe"
                    if etree.QName(protocol).namespace == NFE_NAMESPACE
                    else "infProt/chNFe"
                )
                if protocol.findtext(protocol_path, namespaces=ns) != key:
                    raise AtfArtifactError("atf_invoice_key_mismatch")
            number = node.findtext(path("n:ide/n:nNF"), namespaces=ns) or ""
            if (
                not re.fullmatch(r"[1-9][0-9]{0,8}", number)
                or number.zfill(9) != key[25:34]
            ):
                raise AtfArtifactError("atf_invoice_number_mismatch")
            metadata = {
                "access_key": key,
                "issued_on": issued.isoformat(),
                "model": model,
                "number": number,
            }
            kind = "invoice"
        elif name == "procEventoNFe":
            node = _xml_child(payload, "infEvento")
            if (etree.QName(node).namespace == NFE_NAMESPACE) != qualified:
                raise AtfArtifactError("atf_xml_namespace_invalid")
            key = node.findtext(path("n:chNFe"), namespaces=ns) or ""
            event_type = node.findtext(path("n:tpEvento"), namespaces=ns) or ""
            sequence = int(node.findtext(path("n:nSeqEvento"), namespaces=ns) or "0")
            if (
                node.findtext(path("n:tpAmb"), namespaces=ns) != "1"
                or sequence < 1
                or not re.fullmatch(r"\d{6}", event_type)
            ):
                raise AtfArtifactError("atf_event_scope")
            metadata = {
                "access_key": key,
                "event_type": event_type,
                "sequence": str(sequence),
            }
            kind = "event"
        else:
            raise AtfArtifactError("atf_unsupported_xml")
        if not re.fullmatch(r"[0-9A-Z]{44}", key):
            raise AtfArtifactError("atf_xml_key_invalid")
        if key[6:20] != expected_cnpj:
            raise AtfIdentityMismatch("atf_xml_key_issuer_mismatch")
        if key[20:22] != document_model:
            raise AtfIdentityMismatch("atf_xml_key_model_mismatch")
        metadata["validation_status"] = "pending_schema"
        metadata["namespace_status"] = namespace_status
        return kind, metadata
    except (FiscalSchemaError, ValueError, TypeError):
        raise AtfArtifactError("atf_invalid_xml") from None


def _txt_metadata(
    data: Any, expected_cnpj: Any, period: Any, document_model: str
) -> Any:
    if not data or b"\x00" in data:
        raise AtfArtifactError("atf_empty_or_binary_txt")
    try:
        try:
            text = data.decode("utf-8-sig")
            encoding = "utf-8"
        except UnicodeDecodeError:
            text = data.decode("cp1252")
            encoding = "cp1252"
    except UnicodeDecodeError:
        raise AtfArtifactError("atf_txt_encoding") from None
    lines = sum(bool(line.strip()) for line in text.splitlines())
    if not lines:
        raise AtfArtifactError("atf_empty_txt")
    try:
        rows = csv.DictReader(io.StringIO(text), delimiter="|", strict=True)
        fields = rows.fieldnames or []
        required = {"Chave_de_acesso", "Numero", "Data_de_emissao", "CPF_CNPJ_emit"}
        if not required.issubset(fields) or len(fields) != len(set(fields)):
            raise AtfArtifactError("atf_txt_columns")
        count = 0
        for row in rows:
            if None in row or any(value is None for value in row.values()):
                raise AtfArtifactError("atf_txt_structure")
            key = row["Chave_de_acesso"].strip()
            if normalize_tax_identifier(row["CPF_CNPJ_emit"]) != expected_cnpj:
                raise AtfIdentityMismatch("atf_txt_issuer_mismatch")
            if not re.fullmatch(r"[0-9A-Z]{44}", key):
                raise AtfArtifactError("atf_txt_key_invalid")
            if key[6:20] != expected_cnpj:
                raise AtfIdentityMismatch("atf_txt_key_issuer_mismatch")
            if key[20:22] != document_model:
                raise AtfIdentityMismatch("atf_txt_model_mismatch")
            number = row["Numero"].strip()
            if (
                not number.isdecimal()
                or int(number) < 1
                or number.zfill(9) != key[25:34]
            ):
                raise AtfArtifactError("atf_txt_number_mismatch")
            for layout in ("%d/%m/%Y", "%Y-%m-%d %H:%M:%S"):
                try:
                    issued = datetime.strptime(
                        row["Data_de_emissao"].strip(), layout
                    ).date()
                    break
                except ValueError:
                    continue
            else:
                raise AtfArtifactError("atf_txt_date_invalid")
            if not period.start <= issued <= period.end:
                raise AtfArtifactError("atf_txt_outside_period")
            count += 1
        if not count:
            raise AtfArtifactError("atf_empty_txt")
    except (csv.Error, ValueError, TypeError):
        raise AtfArtifactError("atf_invalid_txt") from None
    return {
        "encoding": encoding,
        "nonempty_lines": str(lines),
        "invoice_count": str(count),
    }


def validate_archive(
    download: Any,
    *,
    company_id: Any,
    period: Any,
    format: Any,
    heartbeat: Any = None,
    document_model: str = "55",
) -> ArchiveValidation:
    try:
        document_profile(document_model)
    except ValueError:
        raise AtfArtifactError("atf_document_model") from None
    company = ClientCompany.objects.get(pk=company_id)
    size = download.staging_path.stat().st_size
    if size != download.byte_count or size > _limit(
        "ATF_MAX_ZIP_BYTES", 200 * 1024 * 1024
    ):
        raise AtfArtifactError("atf_zip_limit")
    with download.staging_path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    if digest != download.sha256 or format not in {"xml", "txt"}:
        raise AtfArtifactError("atf_archive_identity")
    members, seen, total = [], set(), 0
    try:
        with zipfile.ZipFile(download.staging_path) as archive:
            entries = archive.infolist()
            if len(entries) > _limit("ATF_MAX_ZIP_ENTRIES", 50000):
                raise AtfArtifactError("atf_zip_entry_limit")
            for entry in entries:
                if heartbeat:
                    heartbeat()
                name = _member_name(entry.filename)
                if name.casefold() in seen or stat.S_ISLNK(entry.external_attr >> 16):
                    raise AtfArtifactError("atf_unsafe_zip_entry")
                seen.add(name.casefold())
                if entry.is_dir():
                    continue
                if Path(name).suffix.lower() != "." + format:
                    raise AtfArtifactError("atf_archive_format_mismatch")
                cap = (
                    _limit("ATF_MAX_XML_BYTES", 10 * 1024 * 1024)
                    if format == "xml"
                    else _limit("ATF_MAX_TXT_BYTES", 100 * 1024 * 1024)
                )
                if entry.file_size > cap:
                    raise AtfArtifactError("atf_zip_member_limit")
                chunks, count = [], 0
                with archive.open(entry) as source:
                    while chunk := source.read(65536):
                        if heartbeat:
                            heartbeat()
                        count += len(chunk)
                        total += len(chunk)
                        if count > cap or total > _limit(
                            "ATF_MAX_UNCOMPRESSED_BYTES", 1024 * 1024 * 1024
                        ):
                            raise AtfArtifactError("atf_zip_expansion_limit")
                        chunks.append(chunk)
                data = b"".join(chunks)
                kind, metadata = (
                    _xml_metadata(data, company.tax_identifier, period, document_model)
                    if format == "xml"
                    else (
                        "txt",
                        _txt_metadata(
                            data, company.tax_identifier, period, document_model
                        ),
                    )
                )
                members.append(
                    ValidatedMember(
                        name, kind, hashlib.sha256(data).hexdigest(), count, metadata
                    )
                )
    except (
        zipfile.BadZipFile,
        RuntimeError,
        OSError,
        EOFError,
        NotImplementedError,
        zlib.error,
        lzma.LZMAError,
    ):
        raise AtfArtifactError("atf_invalid_zip") from None
    if not members:
        raise AtfArtifactError("atf_empty_archive")
    warnings: tuple[str, ...] = ("pending_schema",) if format == "xml" else ()
    if format == "xml" and any(
        member.metadata.get("namespace_status") != "standard" for member in members
    ):
        warnings += ("nonstandard_xml_namespace",)
    return ArchiveValidation(tuple(members), warnings, digest)


def _publish_original(source: Any, target: Any, expected_digest: Any) -> None:
    target.parent.mkdir(mode=0o750, parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".atf-", dir=target.parent)
    try:
        with os.fdopen(fd, "wb") as output, source.open("rb") as incoming:
            shutil.copyfileobj(incoming, output, 65536)
            output.flush()
            os.fsync(output.fileno())
        with Path(temporary).open("rb") as check:
            if hashlib.file_digest(check, "sha256").hexdigest() != expected_digest:
                raise AtfArtifactError("atf_archive_changed")
        os.chmod(temporary, 0o640)
        os.replace(temporary, target)
    finally:
        Path(temporary).unlink(missing_ok=True)


@transaction.atomic
def persist_archive(
    part_id: Any, ref: Any, download: Any, validation: Any
) -> DownloadArchive:
    part = (
        DownloadPart.objects.select_for_update()
        .select_related("request__company__office")
        .get(pk=part_id)
    )
    if validation.archive_sha256 != download.sha256:
        raise AtfArtifactError("atf_validation_identity")
    existing = DownloadArchive.objects.filter(
        remote_account_key=part.remote_account_key,
        message_id=ref.message_id,
        attachment_index=ref.index,
    ).first()
    if existing:
        if existing.part_id != part.pk or existing.sha256 != download.sha256:
            raise AtfArtifactError("atf_attachment_already_bound")
        return existing
    company_root = company_storage_directory(part.request.company).parent
    relative = (
        company_root
        / "empresas"
        / part.request.company.tax_identifier
        / part.format.upper()
        / part.request.requested_on.strftime("%Y/%m/%d")
        / str(part.request_id)
        / str(part.pk)
        / (download.sha256 + ".zip")
    )
    storage = FiscalStorage()
    _publish_original(
        download.staging_path, storage._safe_target(relative), download.sha256
    )
    result = DownloadArchive.objects.create(
        part=part,
        remote_account_key=part.remote_account_key,
        message_id=ref.message_id,
        attachment_index=ref.index,
        filename=(
            f"{'nfce' if part.request.document_model == '65' else 'nfe'}_"
            f"{part.format}_{part.start_date}_{part.end_date}.zip"
        ),
        path=relative.as_posix(),
        sha256=download.sha256,
        byte_count=download.byte_count,
        warnings=list(validation.warnings),
    )
    return result


def revalidate_archive(archive_id: Any) -> Any:
    from .documents import index_archive

    return index_archive(archive_id)
