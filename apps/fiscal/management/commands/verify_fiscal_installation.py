"""Read-only and opt-in write checks for a local fiscal installation."""

from __future__ import annotations

import os
import stat
from collections.abc import Callable
from pathlib import Path
from typing import Any
from uuid import uuid4

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

from apps.certificates.services.upload_envelope import (
    CertificateUploadEnvelope,
    CertificateUploadEnvelopeError,
)
from apps.certificates.services.vault import CertificateVault, CertificateVaultError
from apps.fiscal.services.storage import FiscalStorage, FiscalStorageError


class FiscalPreflightError(ValueError):
    """A non-secret prerequisite for controlled fiscal operation is missing."""


class Command(BaseCommand):
    help = (
        "Verify local fiscal prerequisites without contacting the SEFAZ. "
        "Use --worker and --write-notes-probe in the worker container."
    )

    def add_arguments(self, parser: Any) -> Any:
        parser.add_argument(
            "--worker",
            action="store_true",
            help="Also verify worker-only certificate secrets and their key pair.",
        )
        parser.add_argument(
            "--write-notes-probe",
            action="store_true",
            help="Atomically write and remove a harmless probe in the notes volume.",
        )

    def handle(self, *args: Any, **options: Any) -> Any:
        failures: list[str] = []
        checks: list[tuple[str, Callable[[], str]]] = [
            ("Banco de dados", self._check_database),
            ("Migrations", self._check_migrations),
            ("Configuração ATF-PB", self._check_atf_configuration),
            ("Volume de notas", self._check_notes_readable),
            ("Chave pública de upload", self._check_upload_public_key),
        ]
        if options["worker"]:
            checks.extend(
                [
                    ("Chave do cofre", self._check_vault_key),
                    ("Par de chaves de upload", self._check_upload_keypair),
                ]
            )
        if options["write_notes_probe"]:
            checks.append(("Escrita atômica no volume", self._check_notes_write))

        for label, check in checks:
            self._run_check(label=label, check=check, failures=failures)

        if failures:
            raise CommandError(
                "A pré-validação fiscal falhou; corrija os itens acima antes de "
                "qualquer operação ATF."
            )
        self.stdout.write(
            self.style.SUCCESS("Pré-validação concluída sem contato com a SEFAZ.")
        )

    def _run_check(
        self,
        *,
        label: str,
        check: Callable[[], str],
        failures: list[str],
    ) -> None:
        try:
            detail = check()
        except FiscalPreflightError as error:
            failures.append(label)
            self.stderr.write(self.style.ERROR(f"[falhou] {label}: {error}"))
        else:
            self.stdout.write(self.style.SUCCESS(f"[ok] {label}: {detail}"))

    @staticmethod
    def _check_database() -> str:
        try:
            connection.ensure_connection()
        except Exception as error:
            raise FiscalPreflightError("a conexão não está disponível") from error
        return "conexão disponível"

    @staticmethod
    def _check_migrations() -> str:
        try:
            executor = MigrationExecutor(connection)
            plan = executor.migration_plan(executor.loader.graph.leaf_nodes())
        except Exception as error:
            raise FiscalPreflightError(
                "não foi possível inspecionar migrations"
            ) from error
        if plan:
            raise FiscalPreflightError(f"há {len(plan)} migration(s) pendente(s)")
        return "nenhuma pendência"

    @staticmethod
    def _check_atf_configuration() -> str:
        if settings.ATF_PB_BASE_URL != "https://www4.sefaz.pb.gov.br":
            raise FiscalPreflightError("endpoint ATF-PB não aprovado")
        connect, read = (
            settings.ATF_CONNECT_TIMEOUT_SECONDS,
            settings.ATF_READ_TIMEOUT_SECONDS,
        )
        if not 0 < connect <= 120 or not 0 < read <= 600:
            raise FiscalPreflightError("timeouts ATF fora dos limites aceitos")
        if settings.ATF_ACCESS_LEASE_SECONDS <= connect + read + 60:
            raise FiscalPreflightError(
                "lease deve exceder os timeouts HTTP e margem de renovação"
            )
        if (
            settings.ATF_POLL_INTERVAL_SECONDS < 60
            or settings.ATF_RETRY_CYCLE_SECONDS < 1800
        ):
            raise FiscalPreflightError("intervalos ATF curtos demais")
        if settings.ATF_WAIT_TIMEOUT_SECONDS < 3600:
            raise FiscalPreflightError("janela de resultado ATF curta demais")
        if settings.ATF_NFCE_WAIT_TIMEOUT_SECONDS < 3600:
            raise FiscalPreflightError("janela de resultado NFC-e curta demais")
        if (
            settings.ATF_NFCE_MAX_POLL_INTERVAL_SECONDS
            < settings.ATF_POLL_INTERVAL_SECONDS
        ):
            raise FiscalPreflightError(
                "intervalo máximo NFC-e menor que o intervalo base"
            )
        if any(
            getattr(settings, name) <= 0
            for name in (
                "ATF_MAX_HTML_BYTES",
                "ATF_MAX_ZIP_BYTES",
                "ATF_MAX_UNCOMPRESSED_BYTES",
                "ATF_MAX_ZIP_ENTRIES",
                "ATF_MAX_XML_BYTES",
                "ATF_MAX_TXT_BYTES",
            )
        ):
            raise FiscalPreflightError("limites de arquivos devem ser positivos")
        return (
            "habilitado" if settings.ATF_PB_ENABLED else "desabilitado; sem tráfego ATF"
        )

    @staticmethod
    def _check_notes_readable() -> str:
        root = settings.FISCAL_NOTES_ROOT
        if not root.is_dir():
            raise FiscalPreflightError("o volume configurado não é um diretório")
        try:
            next(root.iterdir(), None)
        except OSError as error:
            raise FiscalPreflightError("o volume não pode ser lido") from error
        return "diretório acessível"

    @staticmethod
    def _check_upload_public_key() -> str:
        try:
            CertificateUploadEnvelope().encrypt(
                b"preflight",
                request_id=uuid4(),
                purpose="preflight",
            )
        except CertificateUploadEnvelopeError as error:
            raise FiscalPreflightError(
                "a chave pública de upload não está disponível ou é inválida"
            ) from error
        return "válida"

    @staticmethod
    def _check_vault_key() -> str:
        vault = CertificateVault()
        storage_id = f"preflight-{uuid4()}"
        try:
            _require_private_file(vault.key_file)
            encrypted = vault.seal(b"preflight", storage_id)
            if vault.unseal(encrypted, storage_id) != b"preflight":
                raise CertificateVaultError("vault probe could not be verified")
        except CertificateVaultError as error:
            raise FiscalPreflightError(
                "a chave privada do cofre não está disponível ou é inválida"
            ) from error
        return "cifra autenticada validada"

    @staticmethod
    def _check_upload_keypair() -> str:
        envelope = CertificateUploadEnvelope()
        request_id = uuid4()
        try:
            _require_private_file(envelope.private_key_file)
            encrypted = envelope.encrypt(
                b"preflight",
                request_id=request_id,
                purpose="preflight",
            )
            if (
                envelope.decrypt(
                    encrypted,
                    request_id=request_id,
                    purpose="preflight",
                )
                != b"preflight"
            ):
                raise CertificateUploadEnvelopeError("upload keypair probe failed")
        except CertificateUploadEnvelopeError as error:
            raise FiscalPreflightError(
                "o par de chaves de upload não está disponível ou não corresponde"
            ) from error
        return "par correspondente"

    @staticmethod
    def _check_notes_write() -> str:
        try:
            FiscalStorage().probe_writable()
        except FiscalStorageError as error:
            raise FiscalPreflightError(
                "a escrita atômica no volume não foi concluída"
            ) from error
        return "sonda gravada e removida"


def _require_private_file(path: Path) -> None:
    try:
        mode = stat.S_IMODE(path.stat().st_mode)
    except OSError as error:
        raise FiscalPreflightError(
            "um arquivo privado obrigatório está ausente"
        ) from error
    # Windows ACLs are not represented by the POSIX group/other mode bits.
    # Keep the strict check in Linux containers (the production target), while
    # still exercising key presence and cryptographic round-trips on Windows.
    if os.name != "nt" and mode & 0o077:
        raise FiscalPreflightError(
            "um arquivo privado tem permissões de grupo ou outros"
        )
