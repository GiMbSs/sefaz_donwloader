import uuid

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("accounts", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="AuditLog",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("action", models.CharField(max_length=100, verbose_name="ação")),
                ("target", models.CharField(max_length=255, verbose_name="alvo")),
                ("correlation_id", models.UUIDField(blank=True, null=True, verbose_name="correlação")),
                ("payload", models.JSONField(blank=True, default=dict, verbose_name="dados não sensíveis")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="criado em")),
                ("actor", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="audit_entries", to="accounts.user")),
            ],
            options={"verbose_name": "registro de auditoria", "verbose_name_plural": "registros de auditoria", "ordering": ("-created_at",)},
        ),
    ]

