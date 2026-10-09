from django.db import migrations, models


def rename_daily_mode(apps, schema_editor):
    sync_policy = apps.get_model("fiscal", "SyncPolicy")
    sync_policy.objects.filter(mode="daily").update(mode="automatic")


class Migration(migrations.Migration):
    dependencies = [
        (
            "fiscal",
            "0005_rename_fiscal_dist_company_8e09f4_idx_fiscal_dist_company_2055c1_idx_and_more",
        )
    ]

    operations = [
        migrations.AddField(
            model_name="syncpolicy",
            name="frequency",
            field=models.CharField(
                choices=[
                    ("daily", "Diária"),
                    ("weekly", "Semanal"),
                    ("monthly", "Mensal"),
                ],
                default="daily",
                max_length=16,
                verbose_name="recorrência",
            ),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="syncpolicy",
            name="monthday",
            field=models.PositiveSmallIntegerField(default=1, verbose_name="dia do mês"),
            preserve_default=False,
        ),
        migrations.RunPython(rename_daily_mode, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="syncpolicy",
            name="frequency",
            field=models.CharField(
                choices=[
                    ("daily", "Diária"),
                    ("weekly", "Semanal"),
                    ("monthly", "Mensal"),
                ],
                default="daily",
                max_length=16,
                verbose_name="recorrência",
            ),
        ),
        migrations.AlterField(
            model_name="syncpolicy",
            name="monthday",
            field=models.PositiveSmallIntegerField(default=1, verbose_name="dia do mês"),
        ),
        migrations.AlterField(
            model_name="syncpolicy",
            name="mode",
            field=models.CharField(
                choices=[
                    ("automatic", "Automática"), ("manual", "Manual"), ("hybrid", "Híbrida")
                ],
                default="automatic",
                max_length=16,
                verbose_name="modo",
            ),
        ),
        migrations.AlterField(
            model_name="syncpolicy",
            name="scheduled_time",
            field=models.TimeField(blank=True, null=True, verbose_name="horário"),
        ),
        migrations.AlterField(
            model_name="syncpolicy",
            name="weekdays",
            field=models.JSONField(blank=True, default=list, verbose_name="dias da semana"),
        ),
    ]
