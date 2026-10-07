"""Settings for a local Docker installation without a TLS reverse proxy."""

from .production import *  # noqa: F403

# Docker Compose exposes the initial installation only on localhost. A future
# TLS reverse proxy must use config.settings.production instead.
SECURE_SSL_REDIRECT = False
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False

