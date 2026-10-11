from django.db import migrations, models


def classify_existing_documents(apps, schema_editor):
    Document = apps.get_model("fiscal", "FiscalDocument")
    Item = apps.get_model("fiscal", "DistributionItem")
    alias = schema_editor.connection.alias
    for document in Document.objects.using(alias).all().iterator():
        environments = list(
            Item.objects.using(alias)
            .filter(fiscal_document_id=document.pk)
            .values_list("batch__nsu_control__environment", flat=True)
            .distinct()
        )
        # Ambiguous or unlinked historical records retain an explicit legacy scope.
        if len(environments) == 1:
            Document.objects.using(alias).filter(pk=document.pk).update(
                environment=environments[0]
            )


class Migration(migrations.Migration):
    dependencies = [("fiscal", "0006_sync_policy_recurrence")]
    operations = [
        migrations.AddField(
            model_name="fiscaldocument",
            name="environment",
            field=models.CharField(
                blank=True,
                default="",
                max_length=16,
                choices=[("production", "Produção"), ("homologation", "Homologação")],
                verbose_name="ambiente",
            ),
        ),
        migrations.RemoveConstraint(
            model_name="fiscaldocument",
            name="unique_fiscal_document_per_company_access_key",
        ),
        migrations.RunPython(classify_existing_documents, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="fiscaldocument",
            constraint=models.UniqueConstraint(
                fields=("company", "environment", "access_key"),
                name="unique_fiscal_document_per_company_env_key",
            ),
        ),
    ]
