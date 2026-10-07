"""Safe parsing and persistence of NFeDistribuicaoDFe responses.

This module deliberately has no HTTP client. It only accepts bytes obtained by
an approved transport adapter, which keeps production network effects separate
from parsing and state transitions.
"""

from __future__ import annotations

import base64
import binascii
import gzip
import hashlib
import io
from dataclasses import dataclass
from datetime import timedelta
from typing import Iterable

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from lxml import etree

from apps.fiscal.models import (
    DistributionBatch,
    DistributionItem,
    FiscalDocument,
    NsuControl,
)
from apps.fiscal.services.schemas import (
    FiscalSchemaError,
    known_distributed_schema,
    parse_fiscal_xml,
    validate_fiscal_xml,
)
from apps.fiscal.services.storage import FiscalStorage, FiscalStorageError

MAX_COMPRESSED_DOCUMENT_BYTES = 2 * 1024 * 1024
MAX_DECOMPRESSED_DOCUMENT_BYTES = 10 * 1024 * 1024


class DistributionParseError(ValueError):
    pass


@dataclass(frozen=True)
class DecodedDocument:
    nsu: str
    schema_name: str
    compressed_payload: bytes
    xml_payload: bytes


@dataclass(frozen=True)
class DistributionResponse:
    environment: str
    status_code: str
    reason: str
    returned_last_nsu: str
    returned_max_nsu: str
    response_at: str
    documents: tuple[DecodedDocument, ...]


def parse_distribution_response(payload: bytes) -> DistributionResponse:
    try:
        root = validate_fiscal_xml(payload, expected_root="retDistDFeInt")
    except FiscalSchemaError as error:
        raise DistributionParseError(
            "A resposta de distribuição não atende ao schema oficial."
        ) from error

    environment = _required_text(root, "tpAmb")
    status_code = _required_text(root, "cStat")
    reason = _optional_text(root, "xMotivo")
    returned_last_nsu = _optional_text(root, "ultNSU")
    returned_max_nsu = _optional_text(root, "maxNSU")
    response_at = _optional_text(root, "dhResp")
    documents = tuple(_decode_documents(root.findall(".//{*}docZip")))
    return DistributionResponse(
        environment=environment,
        status_code=status_code,
        reason=reason,
        returned_last_nsu=returned_last_nsu,
        returned_max_nsu=returned_max_nsu,
        response_at=response_at,
        documents=documents,
    )


def _required_text(root: etree._Element, name: str) -> str:
    value = _optional_text(root, name)
    if not value:
        raise DistributionParseError(f"Distribution response lacks {name}.")
    return value


def _optional_text(root: etree._Element, name: str) -> str:
    element = root.find(f".//{{*}}{name}")
    return (element.text or "").strip() if element is not None else ""


def _decode_documents(elements: Iterable[etree._Element]) -> Iterable[DecodedDocument]:
    for element in elements:
        nsu = element.get("NSU", "")
        schema_name = element.get("schema", "")
        if not nsu.isdecimal() or not schema_name:
            raise DistributionParseError("docZip lacks NSU or schema metadata.")
        try:
            encoded = b"".join((element.text or "").encode("ascii").split())
        except UnicodeEncodeError as error:
            raise DistributionParseError("docZip has invalid base64 data.") from error
        try:
            compressed = base64.b64decode(encoded, validate=True)
        except (UnicodeEncodeError, binascii.Error) as error:
            raise DistributionParseError("docZip has invalid base64 data.") from error
        if len(compressed) > MAX_COMPRESSED_DOCUMENT_BYTES:
            raise DistributionParseError("docZip exceeds the compressed size limit.")
        try:
            with gzip.GzipFile(fileobj=io.BytesIO(compressed), mode="rb") as gzip_file:
                xml_payload = gzip_file.read(MAX_DECOMPRESSED_DOCUMENT_BYTES + 1)
        except OSError as error:
            raise DistributionParseError("docZip is not a valid gzip payload.") from error
        if len(xml_payload) > MAX_DECOMPRESSED_DOCUMENT_BYTES:
            raise DistributionParseError("docZip exceeds the decompressed size limit.")
        yield DecodedDocument(
            nsu=nsu,
            schema_name=schema_name,
            compressed_payload=compressed,
            xml_payload=xml_payload,
        )


def persist_distribution_response(
    *,
    control_id: int,
    raw_response: bytes,
    soap_response: bytes | None = None,
    sync_request_id: int | None = None,
    storage: FiscalStorage | None = None,
) -> DistributionBatch:
    """Archive the raw response, persist documents, then advance NSU safely."""
    parsed = parse_distribution_response(raw_response)
    response_sha256 = hashlib.sha256(raw_response).hexdigest()
    storage = storage or FiscalStorage()

    created_paths: list[str] = []
    try:
        with transaction.atomic():
            control = (
                NsuControl.objects.select_for_update()
                .select_related("company")
                .get(pk=control_id)
            )
            if parsed.environment != _environment_code(control.environment):
                raise DistributionParseError(
                    "A resposta de distribuição pertence a outro ambiente fiscal."
                )
            existing = DistributionBatch.objects.filter(
                company=control.company,
                response_sha256=response_sha256,
            ).first()
            if existing is not None:
                return existing

            raw_path = storage.write_response(
                control.company_id,
                raw_response,
                category="distribution",
            )
            created_paths.append(raw_path)
            soap_path = ""
            if soap_response is not None:
                soap_path = storage.write_response(
                    control.company_id,
                    soap_response,
                    category="soap",
                )
                created_paths.append(soap_path)
            batch = DistributionBatch.objects.create(
                company=control.company,
                nsu_control=control,
                sync_request_id=sync_request_id,
                response_sha256=response_sha256,
                raw_response_path=raw_path,
                soap_response_path=soap_path,
                status_code=parsed.status_code,
                reason=parsed.reason,
                returned_last_nsu=parsed.returned_last_nsu,
                returned_max_nsu=parsed.returned_max_nsu,
                document_count=len(parsed.documents),
            )
            for document in parsed.documents:
                path = _persist_document(batch=batch, decoded=document, storage=storage)
                if path:
                    created_paths.append(path)

            _advance_control(control, parsed)
            batch.processing_status = DistributionBatch.ProcessingStatus.PROCESSED
            batch.processed_at = timezone.now()
            batch.save(update_fields=("processing_status", "processed_at"))
            return batch
    except Exception:
        for path in reversed(created_paths):
            try:
                storage.delete(path)
            except FiscalStorageError:
                # The original error is more useful to the worker; the storage
                # reconciler can surface an eventual cleanup failure separately.
                pass
        raise


def _persist_document(
    *, batch: DistributionBatch, decoded: DecodedDocument, storage: FiscalStorage
) -> str | None:
    expected_root = known_distributed_schema(decoded.schema_name)
    validation_status = FiscalDocument.ValidationStatus.PENDING_SCHEMA
    validation_error = ""
    try:
        root = (
            validate_fiscal_xml(decoded.xml_payload, expected_root=expected_root)
            if expected_root is not None
            else parse_fiscal_xml(decoded.xml_payload)
        )
        if expected_root is not None:
            validation_status = FiscalDocument.ValidationStatus.VALID
    except FiscalSchemaError:
        root = _parse_inner_xml(decoded.xml_payload)
        validation_status = FiscalDocument.ValidationStatus.INVALID
        validation_error = "O XML distribuído não atende ao schema declarado."
    document_root = etree.QName(root).localname
    access_key = _extract_access_key(root)
    if not access_key:
        DistributionItem.objects.create(
            batch=batch,
            nsu=decoded.nsu,
            schema_name=decoded.schema_name,
            compressed_sha256=hashlib.sha256(decoded.compressed_payload).hexdigest(),
            xml_sha256=hashlib.sha256(decoded.xml_payload).hexdigest(),
            processing_status=DistributionItem.ProcessingStatus.REJECTED,
            processing_error="The document does not expose a supported access key.",
        )
        return None
    model = _extract_model(root, access_key)
    kind = _document_kind(document_root)
    xml_sha256 = hashlib.sha256(decoded.xml_payload).hexdigest()
    relative_path = storage.write_document(
        company_id=batch.company_id,
        model=model,
        access_key=access_key,
        kind=kind,
        discriminator=xml_sha256[:16],
        payload=decoded.xml_payload,
    )
    fiscal_document, created = FiscalDocument.objects.get_or_create(
        company=batch.company,
        access_key=access_key,
        defaults={
            "model": model,
            "kind": kind,
            "schema_name": decoded.schema_name,
            "document_root": document_root,
            "xml_sha256": xml_sha256,
            "xml_path": relative_path,
            "validation_status": validation_status,
            "validation_error": validation_error,
        },
    )
    is_duplicate = not created and fiscal_document.xml_sha256 == xml_sha256
    should_replace = not created and (
        _kind_rank(kind) > _kind_rank(fiscal_document.kind)
        or (
            _kind_rank(kind) == _kind_rank(fiscal_document.kind)
            and fiscal_document.xml_sha256 != xml_sha256
        )
    )
    if should_replace:
        fiscal_document.kind = kind
        fiscal_document.schema_name = decoded.schema_name
        fiscal_document.document_root = document_root
        fiscal_document.xml_sha256 = xml_sha256
        fiscal_document.xml_path = relative_path
        fiscal_document.validation_status = validation_status
        fiscal_document.validation_error = validation_error
        fiscal_document.save(
            update_fields=(
                "kind",
                "schema_name",
                "document_root",
                "xml_sha256",
                "xml_path",
                "validation_status",
                "validation_error",
                "last_received_at",
            )
        )
    DistributionItem.objects.create(
        batch=batch,
        nsu=decoded.nsu,
        schema_name=decoded.schema_name,
        compressed_sha256=hashlib.sha256(decoded.compressed_payload).hexdigest(),
        xml_sha256=xml_sha256,
        fiscal_document=fiscal_document,
        processing_status=(
            DistributionItem.ProcessingStatus.DUPLICATE
            if is_duplicate
            else DistributionItem.ProcessingStatus.STORED
        ),
    )
    return relative_path


def _parse_inner_xml(payload: bytes) -> etree._Element:
    try:
        return parse_fiscal_xml(payload)
    except FiscalSchemaError as error:
        raise DistributionParseError(
            "O XML distribuído não é seguro ou bem-formado."
        ) from error


def _extract_access_key(root: etree._Element) -> str:
    inf_nfe = root.find(".//{*}infNFe")
    if inf_nfe is not None:
        identifier = inf_nfe.get("Id", "")
        if identifier.startswith("NFe"):
            identifier = identifier[3:]
        if _is_access_key(identifier):
            return identifier
    value = _optional_text(root, "chNFe")
    return value if _is_access_key(value) else ""


def _is_access_key(value: str) -> bool:
    return len(value) == 44 and value.isascii() and value.isalnum() and value == value.upper()


def _extract_model(root: etree._Element, access_key: str) -> str:
    model = _optional_text(root, "mod")
    if model.isdecimal() and len(model) == 2:
        return model
    return access_key[20:22]


def _document_kind(root_name: str) -> str:
    if root_name.startswith("res"):
        return FiscalDocument.Kind.SUMMARY
    if root_name.startswith("proc"):
        return FiscalDocument.Kind.COMPLETE
    if "Evento" in root_name or "evento" in root_name:
        return FiscalDocument.Kind.EVENT
    return FiscalDocument.Kind.UNKNOWN


def _kind_rank(kind: str) -> int:
    return {
        FiscalDocument.Kind.UNKNOWN: 0,
        FiscalDocument.Kind.EVENT: 1,
        FiscalDocument.Kind.SUMMARY: 2,
        FiscalDocument.Kind.COMPLETE: 3,
    }.get(kind, 0)


def _advance_control(control: NsuControl, response: DistributionResponse) -> None:
    """Persist only SEFAZ-provided cursors and mandatory cooldowns."""
    control.last_status_code = response.status_code
    control.blocked_reason = ""
    if response.status_code == "656":
        control.next_allowed_at = timezone.now() + timedelta(hours=1)
        control.blocked_reason = response.reason
    else:
        if response.returned_last_nsu:
            if int(response.returned_last_nsu) < int(control.last_nsu or "0"):
                raise DistributionParseError(
                    "A resposta tentou retroceder o cursor NSU."
                )
            control.last_nsu = response.returned_last_nsu
        if response.returned_max_nsu:
            control.maximum_nsu = response.returned_max_nsu
        if response.status_code == "137":
            control.next_allowed_at = timezone.now() + timedelta(hours=1)
            control.blocked_reason = response.reason
        elif (
            response.returned_last_nsu
            and response.returned_last_nsu == response.returned_max_nsu
        ):
            control.next_allowed_at = timezone.now() + timedelta(hours=1)
            control.blocked_reason = "Nenhum novo NSU disponível; aguardar uma hora."
        else:
            control.next_allowed_at = None
    control.save(
        update_fields=(
            "last_nsu",
            "maximum_nsu",
            "last_status_code",
            "blocked_reason",
            "next_allowed_at",
            "updated_at",
        )
    )


def _environment_code(environment: str) -> str:
    return "1" if environment == NsuControl.Environment.PRODUCTION else "2"
