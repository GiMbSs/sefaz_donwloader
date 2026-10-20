from typing import Any

from django.core.management.base import BaseCommand, CommandError

from apps.certificates.services.reconciliation import (
    apply_verified_binding,
    inspect_vault_binding,
)


class Command(BaseCommand):
    help = "Verifica o vínculo do A1 com o cofre; não altera nada sem --apply."

    def add_arguments(self, parser: Any) -> Any:
        parser.add_argument("--certificate-id", type=int, required=True)
        parser.add_argument("--apply", action="store_true")
        parser.add_argument("--actor-id", type=int)

    def handle(self, *args: Any, **options: Any) -> Any:
        result = inspect_vault_binding(options["certificate_id"])
        self.stdout.write(f"state={result.state} candidates={len(result.candidates)}")
        if options["apply"]:
            if not options["actor_id"] or len(result.candidates) != 1:
                raise CommandError("Informe --actor-id e um vínculo único comprovado.")
            apply_verified_binding(
                options["certificate_id"],
                result.candidates[0],
                actor_id=options["actor_id"],
            )
            self.stdout.write("binding_reconciled")
