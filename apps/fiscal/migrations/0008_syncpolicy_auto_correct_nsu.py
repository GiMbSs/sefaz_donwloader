from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("fiscal", "0007_document_environment")]

    operations = [
        migrations.AddField(
            model_name="syncpolicy",
            name="auto_correct_nsu",
            field=models.BooleanField(
                default=False,
                verbose_name="Corrigir automaticamente o NSU divergente",
            ),
        ),
    ]
