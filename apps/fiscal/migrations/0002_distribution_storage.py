from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("fiscal", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="DistributionBatch",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("response_sha256", models.CharField(max_length=64)),
                ("raw_response_path", models.CharField(max_length=255)),
                ("status_code", models.CharField(max_length=8)),
                ("reason", models.TextField(blank=True)),
                ("response_at", models.DateTimeField(blank=True, null=True)),
                ("returned_last_nsu", models.CharField(blank=True, max_length=15)),
                ("returned_max_nsu", models.CharField(blank=True, max_length=15)),
                ("document_count", models.PositiveSmallIntegerField(default=0)),
                ("processing_status", models.CharField(choices=[("received", "Recebido"), ("processed", "Processado"), ("invalid", "Inválido"), ("failed", "Falhou")], default="received", max_length=16)),
                ("processing_error", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("processed_at", models.DateTimeField(blank=True, null=True)),
                ("company", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="distribution_batches", to="organizations.clientcompany")),
                ("nsu_control", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="batches", to="fiscal.nsucontrol")),
                ("sync_request", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="batches", to="fiscal.syncrequest")),
            ],
            options={"verbose_name": "lote de distribuição", "verbose_name_plural": "lotes de distribuição"},
        ),
        migrations.CreateModel(
            name="FiscalDocument",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("access_key", models.CharField(max_length=44)),
                ("model", models.CharField(blank=True, max_length=2)),
                ("kind", models.CharField(choices=[("summary", "Resumo"), ("complete", "Completo"), ("event", "Evento"), ("unknown", "Desconhecido")], default="unknown", max_length=16)),
                ("schema_name", models.CharField(max_length=128)),
                ("document_root", models.CharField(max_length=80)),
                ("xml_sha256", models.CharField(max_length=64)),
                ("xml_path", models.CharField(max_length=255)),
                ("validation_status", models.CharField(choices=[("pending_schema", "Schema pendente"), ("valid", "Válido"), ("invalid", "Inválido")], default="pending_schema", max_length=16)),
                ("validation_error", models.TextField(blank=True)),
                ("first_received_at", models.DateTimeField(auto_now_add=True)),
                ("last_received_at", models.DateTimeField(auto_now=True)),
                ("company", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="fiscal_documents", to="organizations.clientcompany")),
            ],
            options={"verbose_name": "documento fiscal", "verbose_name_plural": "documentos fiscais"},
        ),
        migrations.CreateModel(
            name="DistributionItem",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("nsu", models.CharField(max_length=15)),
                ("schema_name", models.CharField(max_length=128)),
                ("compressed_sha256", models.CharField(max_length=64)),
                ("xml_sha256", models.CharField(blank=True, max_length=64)),
                ("processing_status", models.CharField(choices=[("stored", "Armazenado"), ("rejected", "Rejeitado"), ("duplicate", "Duplicado")], max_length=16)),
                ("processing_error", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("batch", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="items", to="fiscal.distributionbatch")),
                ("fiscal_document", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="distribution_items", to="fiscal.fiscaldocument")),
            ],
            options={"verbose_name": "item de distribuição", "verbose_name_plural": "itens de distribuição"},
        ),
        migrations.AddConstraint(model_name="distributionbatch", constraint=models.UniqueConstraint(fields=("company", "response_sha256"), name="unique_distribution_response_per_company")),
        migrations.AddIndex(model_name="distributionbatch", index=models.Index(fields=["company", "created_at"], name="fiscal_dist_company_8e09f4_idx")),
        migrations.AddIndex(model_name="distributionbatch", index=models.Index(fields=["status_code", "processing_status"], name="fiscal_dist_status__bd2d39_idx")),
        migrations.AddConstraint(model_name="fiscaldocument", constraint=models.UniqueConstraint(fields=("company", "access_key"), name="unique_fiscal_document_per_company_access_key")),
        migrations.AddIndex(model_name="fiscaldocument", index=models.Index(fields=["company", "model", "kind"], name="fiscal_doc_company_3e08c6_idx")),
        migrations.AddIndex(model_name="fiscaldocument", index=models.Index(fields=["validation_status"], name="fiscal_doc_validat_50a49d_idx")),
        migrations.AddConstraint(model_name="distributionitem", constraint=models.UniqueConstraint(fields=("batch", "nsu"), name="unique_nsu_per_distribution_batch")),
        migrations.AddIndex(model_name="distributionitem", index=models.Index(fields=["nsu"], name="fiscal_dist_nsu_9db525_idx")),
    ]
