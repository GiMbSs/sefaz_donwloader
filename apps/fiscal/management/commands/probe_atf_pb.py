"""Explicit ATF login probe; remote fiscal queries require --submit."""

from datetime import date
from typing import Any

from django.core.exceptions import PermissionDenied, ValidationError
from django.core.management.base import BaseCommand, CommandError

from apps.fiscal.atf.client import open_atf_client
from apps.fiscal.atf.errors import AtfError
from apps.fiscal.atf.types import Period
from apps.fiscal.services.downloads import request_download
from apps.organizations.models import ClientCompany


class Command(BaseCommand):
    help = "Validate A1 login and mailbox access; submit only with explicit period."

    def add_arguments(self, parser: Any) -> Any:
        parser.add_argument("--company-id", type=int, required=True)
        parser.add_argument("--submit", action="store_true")
        parser.add_argument("--actor-id", type=int)
        parser.add_argument("--start-date", type=date.fromisoformat)
        parser.add_argument("--end-date", type=date.fromisoformat)
        parser.add_argument("--format", choices=["xml", "txt", "both"], default="both")
        parser.add_argument("--document-model", choices=["55", "65"], default="55")

    def handle(self, *args: Any, **options: Any) -> Any:
        if options["submit"]:
            if not all(options[key] for key in ("actor_id", "start_date", "end_date")):
                raise CommandError("--submit exige ator, data inicial e data final.")
            try:
                result = request_download(
                    company_id=options["company_id"],
                    document_model=options["document_model"],
                    period=Period(options["start_date"], options["end_date"]),
                    formats=("xml", "txt")
                    if options["format"] == "both"
                    else (options["format"],),
                    actor_id=options["actor_id"],
                    trigger="manual",
                )
            except (
                ValidationError,
                ValueError,
                PermissionDenied,
                ClientCompany.DoesNotExist,
            ):
                raise CommandError(
                    "Pedido inválido ou acesso não autorizado."
                ) from None
            self.stdout.write(f"Pedido registrado: {result.pk}")
            return
        try:
            with open_atf_client(options["company_id"]) as client:
                page = client.list_messages()
                self.stdout.write(
                    "A1 autenticado; caixa acessível "
                    f"({len(page.items)} grupos nesta página)."
                )
        except (AtfError, ClientCompany.DoesNotExist):
            raise CommandError(
                "Não foi possível validar o acesso ATF; "
                "confira certificado e configuração."
            ) from None
