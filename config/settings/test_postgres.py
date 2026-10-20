import os

from .test import *  # noqa: F403

_database = os.environ.get("TEST_POSTGRES_DB", "test_sefaz_atf")
if not _database.startswith("test_"):
    raise ValueError("TEST_POSTGRES_DB must identify a disposable test database")
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": _database,
        "USER": os.environ.get("TEST_POSTGRES_USER", "postgres"),
        "PASSWORD": os.environ.get("TEST_POSTGRES_PASSWORD", ""),
        "HOST": os.environ.get("TEST_POSTGRES_HOST", "127.0.0.1"),
        "PORT": os.environ.get("TEST_POSTGRES_PORT", "15432"),
        "TEST": {"NAME": _database},
    }
}
