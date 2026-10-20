from typing import Any

from django.core.management.base import BaseCommand

from apps.fiscal.services.download_recovery import recover_download_request


class Command(BaseCommand):
    help = "Retoma etapas persistidas sem reenviar uma consulta incerta."

    def add_arguments(self, parser: Any) -> Any:
        parser.add_argument("request_id")
        parser.add_argument("--actor-id", type=int, required=True)
        parser.add_argument("--note", required=True)

    def handle(self, *args: Any, **options: Any) -> Any:
        result = recover_download_request(
            options["request_id"], actor_id=options["actor_id"], note=options["note"]
        )
        self.stdout.write(
            f"resumed={len(result.resumed_parts)} review={result.requires_review}"
        )
