import os
from pathlib import Path

from .base import *  # noqa: F403

SECRET_KEY = SECRET_KEY or "development-only-secret-key-not-for-production"  # noqa: F405
DEBUG = True
ALLOWED_HOSTS = ALLOWED_HOSTS or ["localhost", "127.0.0.1", "testserver"]  # noqa: F405

DEV_MODE = os.environ.get("DEV_MODE", "").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}

if DEV_MODE:
    DATABASES = {  # noqa: F405
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "dev.sqlite3",  # noqa: F405
        }
    }
    # Keep direct development files in the current user's private profile, not
    # in the shared project folder. The Docker paths from a copied .env
    # (``/dados/...``) are deliberately not reused here: they exist only inside
    # containers and would make local A1 uploads fail before the worker can
    # validate the certificate.
    DEV_RUNTIME_ROOT = Path(
        os.environ.get("DEV_STORAGE_ROOT", Path.home() / ".sefaz_downloader")
    )

    def _local_path(name: str, default: Path) -> Path:
        configured = os.environ.get(name)
        if configured and not configured.startswith("/dados/"):
            return Path(configured)
        return default

    FISCAL_NOTES_ROOT = _local_path("NOTES_STORAGE_ROOT", DEV_RUNTIME_ROOT / "notes")
    CERTIFICATE_VAULT_ROOT = _local_path(
        "CERTIFICATE_STORAGE_ROOT", DEV_RUNTIME_ROOT / "certificates"
    )
    CERTIFICATE_ENCRYPTION_KEY_FILE = _local_path(
        "CERTIFICATE_ENCRYPTION_KEY_FILE",
        CERTIFICATE_VAULT_ROOT / ".secrets" / "certificate-vault.key",
    )
    CERTIFICATE_UPLOAD_PRIVATE_KEY_FILE = _local_path(
        "CERTIFICATE_UPLOAD_PRIVATE_KEY_FILE",
        CERTIFICATE_VAULT_ROOT / ".secrets" / "certificate-upload-private.key",
    )
    CERTIFICATE_UPLOAD_PUBLIC_KEY_FILE = _local_path(
        "CERTIFICATE_UPLOAD_PUBLIC_KEY_FILE",
        DEV_RUNTIME_ROOT / "certificate-public" / "certificate-upload-public.key",
    )

