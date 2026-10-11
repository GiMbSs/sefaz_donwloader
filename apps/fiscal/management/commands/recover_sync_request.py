from django.core.management.base import BaseCommand, CommandError

from apps.accounts.models import User
from apps.fiscal.services.recovery import (
    SynchronizationRecoveryError,
    recover_interrupted_request,
)


class Command(BaseCommand):
    help = "Encerra um pedido interrompido após parada confirmada do worker."

    def add_arguments(self, parser):
        parser.add_argument("--request-id", type=int, required=True)
        parser.add_argument("--actor-email", required=True)
        parser.add_argument("--reason", required=True)
        parser.add_argument("--confirm-worker-stopped", action="store_true")

    def handle(self, *args, **options):
        actor = User.objects.filter(
            email=options["actor_email"], is_active=True
        ).first()
        if actor is None:
            raise CommandError("Administrador ativo não encontrado.")
        try:
            request = recover_interrupted_request(
                request_id=options["request_id"],
                actor=actor,
                reason=options["reason"],
                worker_stopped=options["confirm_worker_stopped"],
            )
        except SynchronizationRecoveryError as error:
            raise CommandError(str(error)) from error
        self.stdout.write(
            self.style.SUCCESS(
                f"Solicitação {request.pk}: {request.get_status_display()}. "
                "Nenhuma nova consulta foi enviada à SEFAZ."
            )
        )
