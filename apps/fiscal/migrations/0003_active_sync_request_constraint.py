from django.db import migrations, models
from django.db.models import Q


class Migration(migrations.Migration):
    dependencies = [
        ("fiscal", "0002_distribution_storage"),
    ]

    operations = [
        migrations.AddConstraint(
            model_name="syncrequest",
            constraint=models.UniqueConstraint(
                condition=Q(status__in=("queued", "running", "waiting")),
                fields=("company", "environment"),
                name="one_active_sync_request_per_company_environment",
            ),
        ),
    ]
