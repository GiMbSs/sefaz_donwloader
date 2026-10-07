from django.db import migrations, models

import apps.organizations.validators


class Migration(migrations.Migration):
    dependencies = [
        ("organizations", "0001_initial"),
    ]

    operations = [
        migrations.AlterField(
            model_name="accountingoffice",
            name="tax_identifier",
            field=models.CharField(
                max_length=14,
                unique=True,
                validators=[apps.organizations.validators.validate_tax_identifier],
                verbose_name="CNPJ",
            ),
        ),
        migrations.AlterField(
            model_name="clientcompany",
            name="tax_identifier",
            field=models.CharField(
                max_length=14,
                validators=[apps.organizations.validators.validate_tax_identifier],
                verbose_name="CNPJ",
            ),
        ),
    ]

