from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("accounts", "0001_initial"),
        ("organizations", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="SyncPolicy",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("mode", models.CharField(choices=[("daily", "Automática diária"), ("manual", "Manual"), ("hybrid", "Híbrida")], default="daily", max_length=16, verbose_name="modo")),
                ("scheduled_time", models.TimeField(blank=True, null=True, verbose_name="horário diário")),
                ("timezone", models.CharField(default="America/Fortaleza", max_length=64, verbose_name="fuso horário")),
                ("weekdays", models.JSONField(blank=True, default=list, verbose_name="dias ativos")),
                ("is_active", models.BooleanField(default=True, verbose_name="ativa")),
                ("last_requested_at", models.DateTimeField(blank=True, null=True, verbose_name="última solicitação")),
                ("last_finished_at", models.DateTimeField(blank=True, null=True, verbose_name="última conclusão")),
                ("last_result", models.CharField(blank=True, max_length=32, verbose_name="último resultado")),
                ("failure_count", models.PositiveIntegerField(default=0, verbose_name="falhas consecutivas")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="criada em")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="atualizada em")),
                ("company", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="sync_policy", to="organizations.clientcompany")),
            ],
            options={"verbose_name": "política de sincronização", "verbose_name_plural": "políticas de sincronização"},
        ),
        migrations.CreateModel(
            name="NsuControl",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("environment", models.CharField(choices=[("production", "Produção"), ("homologation", "Homologação")], max_length=16, verbose_name="ambiente")),
                ("service", models.CharField(default="nfe_distribution", max_length=64, verbose_name="serviço")),
                ("last_nsu", models.CharField(blank=True, max_length=15, verbose_name="último NSU")),
                ("maximum_nsu", models.CharField(blank=True, max_length=15, verbose_name="máximo NSU")),
                ("next_allowed_at", models.DateTimeField(blank=True, null=True, verbose_name="próxima consulta permitida")),
                ("blocked_reason", models.CharField(blank=True, max_length=255, verbose_name="motivo do bloqueio")),
                ("last_status_code", models.CharField(blank=True, max_length=8, verbose_name="último cStat")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="atualizado em")),
                ("company", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="nsu_controls", to="organizations.clientcompany")),
            ],
            options={"verbose_name": "controle de NSU", "verbose_name_plural": "controles de NSU"},
        ),
        migrations.CreateModel(
            name="SyncRequest",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("environment", models.CharField(choices=[("production", "Produção"), ("homologation", "Homologação")], max_length=16, verbose_name="ambiente")),
                ("trigger", models.CharField(choices=[("scheduled", "Agendada"), ("manual", "Manual")], max_length=16, verbose_name="origem")),
                ("status", models.CharField(choices=[("queued", "Na fila"), ("running", "Em execução"), ("waiting", "Aguardando SEFAZ"), ("succeeded", "Concluída"), ("failed", "Falhou"), ("coalesced", "Agrupada")], default="queued", max_length=16, verbose_name="situação")),
                ("requested_at", models.DateTimeField(auto_now_add=True, verbose_name="solicitada em")),
                ("started_at", models.DateTimeField(blank=True, null=True, verbose_name="iniciada em")),
                ("finished_at", models.DateTimeField(blank=True, null=True, verbose_name="finalizada em")),
                ("result_detail", models.TextField(blank=True, verbose_name="detalhe do resultado")),
                ("company", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="sync_requests", to="organizations.clientcompany")),
                ("requested_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="requested_syncs", to="accounts.user")),
            ],
            options={"verbose_name": "solicitação de sincronização", "verbose_name_plural": "solicitações de sincronização"},
        ),
        migrations.AddConstraint(
            model_name="nsucontrol",
            constraint=models.UniqueConstraint(fields=("company", "environment", "service"), name="unique_nsu_control_per_company_environment_service"),
        ),
        migrations.AddIndex(
            model_name="nsucontrol",
            index=models.Index(fields=["next_allowed_at"], name="fiscal_nsuc_next_al_c3502e_idx"),
        ),
        migrations.AddIndex(
            model_name="syncrequest",
            index=models.Index(fields=["company", "status", "requested_at"], name="fiscal_sync_company_481d49_idx"),
        ),
    ]

