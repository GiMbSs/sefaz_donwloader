import base64
import os
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Generate the 32-byte private key used by the certificate vault."

    def add_arguments(self, parser):  # type: ignore[no-untyped-def]
        parser.add_argument("--path", type=Path, default=settings.CERTIFICATE_ENCRYPTION_KEY_FILE)

    def handle(self, *args, **options):  # type: ignore[no-untyped-def]
        path: Path = options["path"]
        if path.exists():
            raise CommandError(f"Refusing to overwrite existing key file: {path}")
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as key_file:
            key_file.write(base64.urlsafe_b64encode(os.urandom(32)))
            key_file.write(b"\n")
        self.stdout.write(self.style.SUCCESS(f"Certificate vault key created at {path}"))

