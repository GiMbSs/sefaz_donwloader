from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("fiscal", "0003_active_sync_request_constraint")]

    operations = [
        migrations.AddField(
            model_name="distributionbatch",
            name="soap_response_path",
            field=models.CharField(blank=True, max_length=255),
        ),
    ]
