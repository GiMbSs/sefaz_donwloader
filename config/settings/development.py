import os

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

