from django.db import migrations, models


def rename_paused_companies(apps, schema_editor):
    client_company = apps.get_model("organizations", "ClientCompany")
    client_company.objects.filter(status="paused").update(status="inactive")


class Migration(migrations.Migration):
    dependencies = [
        (
            "organizations",
            "0004_rename_organizations_office__a3572d_idx_organizatio_office__26c3f5_idx",
        )
    ]

    operations = [
        migrations.AddField(
            model_name="clientcompany",
            name="fiscal_environment",
            field=models.CharField(
                choices=[("production", "Produção"), ("homologation", "Homologação")],
                default="production",
                max_length=16,
                verbose_name="ambiente fiscal",
            ),
            preserve_default=False,
        ),
        migrations.RunPython(rename_paused_companies, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="clientcompany",
            name="fiscal_environment",
            field=models.CharField(
                choices=[("production", "Produção"), ("homologation", "Homologação")],
                default="homologation",
                max_length=16,
                verbose_name="ambiente fiscal",
            ),
        ),
        migrations.AlterField(
            model_name="clientcompany",
            name="status",
            field=models.CharField(
                choices=[
                    ("active", "Ativa"),
                    ("inactive", "Inativa"),
                    ("archived", "Arquivada"),
                ],
                default="active",
                max_length=16,
                verbose_name="situação",
            ),
        ),
    ]
