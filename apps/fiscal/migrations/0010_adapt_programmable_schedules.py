from django.db import migrations


def forwards(apps, schema_editor):
    old = apps.get_model("fiscal", "SyncPolicy")
    new = apps.get_model("fiscal", "DownloadPolicy")
    for policy in old.objects.all().iterator():
        strategy = {"daily": "previous_day", "weekly": "rolling_days", "monthly": "previous_month"}[policy.frequency]
        new.objects.get_or_create(company_id=policy.company_id, defaults={
            "legacy_policy_id": policy.pk, "mode": policy.mode,
            "frequency": policy.frequency, "scheduled_time": policy.scheduled_time,
            "timezone": policy.timezone, "weekdays": policy.weekdays, "monthday": policy.monthday,
            "is_active": policy.is_active, "period_strategy": strategy, "rolling_days": 7,
            "formats": ["xml", "txt"],
        })


class Migration(migrations.Migration):
    dependencies = [("fiscal", "0009_atf_download_domain")]
    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
