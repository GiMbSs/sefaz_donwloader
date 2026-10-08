import base64
import os
from io import StringIO
from pathlib import Path

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import override_settings

from apps.certificates.services.upload_envelope import generate_upload_keypair


SCHEMA_ROOT = Path(__file__).resolve().parents[1] / "vendor" / "sefaz-schemas"


def _preflight_settings(tmp_path: Path) -> dict[str, Path]:
    notes_root = tmp_path / "notes"
    notes_root.mkdir()
    vault_root = tmp_path / "certificates"
    vault_key = vault_root / ".secrets" / "certificate-vault.key"
    vault_key.parent.mkdir(parents=True)
    vault_key.write_bytes(base64.urlsafe_b64encode(b"p" * 32))
    os.chmod(vault_key, 0o600)
    private_key = vault_root / ".secrets" / "certificate-upload-private.key"
    public_key = tmp_path / "certificate-public" / "certificate-upload-public.key"
    generate_upload_keypair(
        private_key_file=private_key,
        public_key_file=public_key,
    )
    return {
        "FISCAL_NOTES_ROOT": notes_root,
        "CERTIFICATE_VAULT_ROOT": vault_root,
        "CERTIFICATE_ENCRYPTION_KEY_FILE": vault_key,
        "CERTIFICATE_UPLOAD_PRIVATE_KEY_FILE": private_key,
        "CERTIFICATE_UPLOAD_PUBLIC_KEY_FILE": public_key,
    }


@pytest.mark.django_db
def test_worker_preflight_checks_local_dependencies_without_retaining_probe(
    tmp_path: Path,
) -> None:
    configured = _preflight_settings(tmp_path)
    output = StringIO()

    with override_settings(FISCAL_SCHEMA_ROOT=SCHEMA_ROOT, **configured):
        call_command(
            "verify_fiscal_installation",
            "--worker",
            "--write-notes-probe",
            stdout=output,
        )

    assert "Pré-validação concluída sem contato com a SEFAZ." in output.getvalue()
    assert list(configured["FISCAL_NOTES_ROOT"].iterdir()) == []


@pytest.mark.django_db
def test_preflight_rejects_a_schema_manifest_with_an_invalid_checksum(
    tmp_path: Path,
) -> None:
    configured = _preflight_settings(tmp_path)
    schema_root = tmp_path / "schemas"
    schema_directory = schema_root / "distribuicao"
    schema_directory.mkdir(parents=True)
    (schema_directory / "test.xsd").write_text("schema", encoding="utf-8")
    (schema_root / "SHA256SUMS").write_text(
        f"{'0' * 64}  distribuicao/test.xsd\n",
        encoding="utf-8",
    )

    with override_settings(FISCAL_SCHEMA_ROOT=schema_root, **configured):
        with pytest.raises(CommandError):
            call_command("verify_fiscal_installation", stdout=StringIO())
