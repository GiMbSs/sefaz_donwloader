from .base import *  # noqa: F403

SECRET_KEY = SECRET_KEY or "development-only-secret-key-not-for-production"  # noqa: F405
DEBUG = True
ALLOWED_HOSTS = ALLOWED_HOSTS or ["localhost", "127.0.0.1", "testserver"]  # noqa: F405

