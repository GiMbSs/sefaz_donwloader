from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="AccountingOffice",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("legal_name", models.CharField(max_length=255, verbose_name="razão social")),
                ("tax_identifier", models.CharField(max_length=14, unique=True, verbose_name="CNPJ")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="criado em")),
            ],
            options={"verbose_name": "escritório contábil", "verbose_name_plural": "escritórios contábeis"},
        ),
        migrations.CreateModel(
            name="ClientCompany",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("legal_name", models.CharField(max_length=255, verbose_name="razão social")),
                ("tax_identifier", models.CharField(max_length=14, verbose_name="CNPJ")),
                ("state_registration", models.CharField(blank=True, max_length=32, verbose_name="inscrição estadual")),
                ("state", models.CharField(default="PB", max_length=2, verbose_name="UF")),
                ("status", models.CharField(choices=[("active", "Ativa"), ("paused", "Pausada"), ("archived", "Arquivada")], default="active", max_length=16, verbose_name="situação")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="criado em")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="atualizado em")),
                ("office", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="companies", to="organizations.accountingoffice")),
            ],
            options={"verbose_name": "empresa cliente", "verbose_name_plural": "empresas clientes"},
        ),
        migrations.AddConstraint(
            model_name="clientcompany",
            constraint=models.UniqueConstraint(fields=("office", "tax_identifier"), name="unique_company_tax_identifier_per_office"),
        ),
        migrations.AddIndex(
            model_name="clientcompany",
            index=models.Index(fields=["office", "status"], name="organizations_office__a3572d_idx"),
        ),
    ]

