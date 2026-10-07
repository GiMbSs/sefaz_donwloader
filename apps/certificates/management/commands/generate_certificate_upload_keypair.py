from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.certificates.services.upload_envelope import (
    CertificateUploadEnvelopeError,
    generate_upload_keypair,
)


class Command(BaseCommand):
    help = "Generate the worker-only X25519 keypair for certificate uploads."

    def add_arguments(self, parser):  # type: ignore[no-untyped-def]
        parser.add_argument(
            "--private-path",
            type=Path,
            default=settings.CERTIFICATE_UPLOAD_PRIVATE_KEY_FILE,
        )
        parser.add_argument(
            "--public-path",
            type=Path,
            default=settings.CERTIFICATE_UPLOAD_PUBLIC_KEY_FILE,
        )
        parser.add_argument("--if-missing", action="store_true")

    def handle(self, *args, **options):  # type: ignore[no-untyped-def]
        try:
            created = generate_upload_keypair(
                private_key_file=options["private_path"],
                public_key_file=options["public_path"],
                if_missing=options["if_missing"],
            )
        except CertificateUploadEnvelopeError as error:
            raise CommandError(str(error)) from error
        if created:
            self.stdout.write(self.style.SUCCESS("Certificate upload keypair created."))
        else:
            self.stdout.write("Certificate upload keypair already exists.")
