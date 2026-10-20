"""Settings shared by every environment."""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent


def _load_project_environment() -> None:
    """Load simple local settings without allowing them to override real env vars.

    Docker Compose injects its environment before Django starts.  Direct local
    commands do not, so reading the ignored project ``.env`` here keeps both
    execution modes consistent while preserving the process environment as the
    highest-priority source.
    """

    environment_file = BASE_DIR / ".env"
    try:
        lines = environment_file.read_text(encoding="utf-8").splitlines()
    except OSError:
        return
    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line.removeprefix("export ").lstrip()
        key, separator, value = line.partition("=")
        key = key.strip()
        if not separator or not key.isidentifier():
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        os.environ.setdefault(key, value)


_load_project_environment()

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "")
DEBUG = False

ALLOWED_HOSTS = [
    host.strip()
    for host in os.environ.get("DJANGO_ALLOWED_HOSTS", "").split(",")
    if host.strip()
]
CSRF_TRUSTED_ORIGINS = [
    origin.strip()
    for origin in os.environ.get("DJANGO_CSRF_TRUSTED_ORIGINS", "").split(",")
    if origin.strip()
]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "apps.accounts.apps.AccountsConfig",
    "apps.certificates.apps.CertificatesConfig",
    "apps.organizations.apps.OrganizationsConfig",
    "apps.fiscal.apps.FiscalConfig",
    "apps.operations.apps.OperationsConfig",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

if os.environ.get("DJANGO_USE_SQLITE") == "1":
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": os.environ.get("POSTGRES_DB", "sefaz_downloader"),
            "USER": os.environ.get("POSTGRES_USER", "sefaz_downloader"),
            "PASSWORD": os.environ.get("POSTGRES_PASSWORD", ""),
            "HOST": os.environ.get("DB_HOST", "127.0.0.1"),
            "PORT": os.environ.get("DB_PORT", "5432"),
            "CONN_MAX_AGE": 60,
        }
    }

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": (
            "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"
        )
    },
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "pt-br"
TIME_ZONE = "America/Fortaleza"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"
    },
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
AUTH_USER_MODEL = "accounts.User"
LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "dashboard"

DATA_UPLOAD_MAX_MEMORY_SIZE = 2 * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 2 * 1024 * 1024

FISCAL_NOTES_ROOT = Path(os.environ.get("NOTES_STORAGE_ROOT", "/dados/notas"))
# Only the observed SEFAZ-PB ATF endpoint is supported.
ATF_PB_ENABLED = os.environ.get("ATF_PB_ENABLED", "False").lower() in {
    "true",
    "1",
    "yes",
}
ATF_PB_BASE_URL = "https://www4.sefaz.pb.gov.br"
ATF_CONNECT_TIMEOUT_SECONDS = float(os.environ.get("ATF_CONNECT_TIMEOUT_SECONDS", "10"))
ATF_READ_TIMEOUT_SECONDS = float(os.environ.get("ATF_READ_TIMEOUT_SECONDS", "120"))
ATF_TLS_CA_BUNDLE = os.environ.get("ATF_TLS_CA_BUNDLE", "")
ATF_POLL_INTERVAL_SECONDS = int(os.environ.get("ATF_POLL_INTERVAL_SECONDS", "60"))
ATF_ACCESS_LEASE_SECONDS = int(os.environ.get("ATF_ACCESS_LEASE_SECONDS", "300"))
ATF_WAIT_TIMEOUT_SECONDS = int(os.environ.get("ATF_WAIT_TIMEOUT_SECONDS", "86400"))
ATF_NFCE_WAIT_TIMEOUT_SECONDS = int(
    os.environ.get("ATF_NFCE_WAIT_TIMEOUT_SECONDS", "604800")
)
ATF_NFCE_MAX_POLL_INTERVAL_SECONDS = int(
    os.environ.get("ATF_NFCE_MAX_POLL_INTERVAL_SECONDS", "900")
)
ATF_RETRY_CYCLE_SECONDS = int(os.environ.get("ATF_RETRY_CYCLE_SECONDS", "1800"))
ATF_MAX_HTML_BYTES = int(os.environ.get("ATF_MAX_HTML_BYTES", str(10 * 1024 * 1024)))
ATF_MAX_ZIP_BYTES = int(os.environ.get("ATF_MAX_ZIP_BYTES", str(200 * 1024 * 1024)))
ATF_MAX_UNCOMPRESSED_BYTES = int(
    os.environ.get("ATF_MAX_UNCOMPRESSED_BYTES", str(1024 * 1024 * 1024))
)
ATF_MAX_ZIP_ENTRIES = int(os.environ.get("ATF_MAX_ZIP_ENTRIES", "50000"))
ATF_MAX_XML_BYTES = int(os.environ.get("ATF_MAX_XML_BYTES", str(10 * 1024 * 1024)))
ATF_MAX_TXT_BYTES = int(os.environ.get("ATF_MAX_TXT_BYTES", str(100 * 1024 * 1024)))
CERTIFICATE_VAULT_ROOT = Path(
    os.environ.get("CERTIFICATE_STORAGE_ROOT", "/dados/certificados")
)
CERTIFICATE_ENCRYPTION_KEY_FILE = Path(
    os.environ.get(
        "CERTIFICATE_ENCRYPTION_KEY_FILE",
        CERTIFICATE_VAULT_ROOT / ".secrets" / "certificate-vault.key",
    )
)
CERTIFICATE_MAX_UPLOAD_BYTES = int(
    os.environ.get("CERTIFICATE_MAX_UPLOAD_BYTES", str(5 * 1024 * 1024))
)
CERTIFICATE_UPLOAD_PRIVATE_KEY_FILE = Path(
    os.environ.get(
        "CERTIFICATE_UPLOAD_PRIVATE_KEY_FILE",
        CERTIFICATE_VAULT_ROOT / ".secrets" / "certificate-upload-private.key",
    )
)
CERTIFICATE_UPLOAD_PUBLIC_KEY_FILE = Path(
    os.environ.get(
        "CERTIFICATE_UPLOAD_PUBLIC_KEY_FILE",
        "/dados/certificate-public/certificate-upload-public.key",
    )
)
CERTIFICATE_UPLOAD_STAGING_SECONDS = int(
    os.environ.get("CERTIFICATE_UPLOAD_STAGING_SECONDS", "900")
)

CELERY_BROKER_URL = os.environ.get("REDIS_URL", "redis://127.0.0.1:6379/0")
CELERY_RESULT_BACKEND = CELERY_BROKER_URL
CELERY_TASK_SERIALIZER = "json"
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_RESULT_SERIALIZER = "json"
CELERY_TIMEZONE = TIME_ZONE
CELERY_BEAT_SCHEDULE = {
    "queue-due-atf-downloads": {
        "task": "apps.fiscal.tasks.schedule_due_downloads",
        "schedule": 300.0,
    },
    "expire-staged-certificate-uploads": {
        "task": "apps.certificates.tasks.expire_staged_certificate_uploads_task",
        "schedule": 300.0,
    },
}

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": os.environ.get("LOG_LEVEL", "INFO")},
}
