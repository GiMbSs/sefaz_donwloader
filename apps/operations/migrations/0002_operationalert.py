from django.db import migrations, models
from django.db.models import Q
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0001_initial"),
        ("operations", "0001_initial"),
        ("organizations", "0003_officemembership"),
    ]

    operations = [
        migrations.CreateModel(
            name="OperationAlert",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("code", models.CharField(max_length=80, verbose_name="código")),
                (
                    "severity",
                    models.CharField(
                        choices=[
                            ("info", "Informativo"),
                            ("warning", "Atenção"),
                            ("critical", "Crítico"),
                        ],
                        default="warning",
                        max_length=16,
                        verbose_name="gravidade",
                    ),
                ),
                ("title", models.CharField(max_length=160, verbose_name="título")),
                ("message", models.TextField(verbose_name="mensagem")),
                (
                    "context",
                    models.JSONField(blank=True, default=dict, verbose_name="contexto não sensível"),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[("open", "Aberto"), ("resolved", "Resolvido")],
                        default="open",
                        max_length=16,
                        verbose_name="situação",
                    ),
                ),
                ("resolved_at", models.DateTimeField(blank=True, null=True, verbose_name="resolvido em")),
                ("resolution_note", models.TextField(blank=True, verbose_name="registro da resolução")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="criado em")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="atualizado em")),
                (
                    "company",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="operation_alerts",
                        to="organizations.clientcompany",
                    ),
                ),
                (
                    "resolved_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="resolved_operation_alerts",
                        to="accounts.user",
                    ),
                ),
            ],
            options={
                "verbose_name": "alerta operacional",
                "verbose_name_plural": "alertas operacionais",
                "ordering": ("-created_at",),
            },
        ),
        migrations.AddConstraint(
            model_name="operationalert",
            constraint=models.UniqueConstraint(
                condition=Q(status="open"),
                fields=("company", "code"),
                name="one_open_operation_alert_per_company_code",
            ),
        ),
        migrations.AddIndex(
            model_name="operationalert",
            index=models.Index(
                fields=["company", "status", "created_at"],
                name="operations__company_236d50_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="operationalert",
            index=models.Index(
                fields=["severity", "status"],
                name="operations__severit_7f9c8d_idx",
            ),
        ),
    ]
