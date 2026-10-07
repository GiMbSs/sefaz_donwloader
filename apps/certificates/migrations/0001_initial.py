import uuid

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
from django.db.models import Q


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("organizations", "0002_cnpj_validators"),
    ]

    operations = [
        migrations.CreateModel(
            name="DigitalCertificate",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("storage_id", models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
                ("encrypted_path", models.CharField(editable=False, max_length=255, unique=True)),
                ("sealed_password", models.TextField(editable=False)),
                ("filename", models.CharField(max_length=255, verbose_name="nome original")),
                ("content_sha256", models.CharField(editable=False, max_length=64)),
                ("certificate_fingerprint_sha256", models.CharField(editable=False, max_length=64)),
                ("serial_number", models.CharField(editable=False, max_length=128)),
                ("subject", models.TextField(editable=False)),
                ("issuer", models.TextField(editable=False)),
                ("not_valid_before", models.DateTimeField(editable=False)),
                ("not_valid_after", models.DateTimeField(editable=False)),
                ("status", models.CharField(choices=[("active", "Ativo"), ("replaced", "Substituído"), ("expired", "Expirado"), ("invalid", "Inválido")], default="active", max_length=16)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("replaced_at", models.DateTimeField(blank=True, null=True)),
                ("company", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="digital_certificates", to="organizations.clientcompany")),
                ("uploaded_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="uploaded_certificates", to=settings.AUTH_USER_MODEL)),
            ],
            options={"verbose_name": "certificado digital", "verbose_name_plural": "certificados digitais", "ordering": ("-not_valid_after", "-created_at")},
        ),
        migrations.AddConstraint(
            model_name="digitalcertificate",
            constraint=models.UniqueConstraint(condition=Q(("status", "active")), fields=("company",), name="one_active_certificate_per_company"),
        ),
        migrations.AddIndex(
            model_name="digitalcertificate",
            index=models.Index(fields=["company", "status"], name="certificates_company_7cbbfc_idx"),
        ),
        migrations.AddIndex(
            model_name="digitalcertificate",
            index=models.Index(fields=["not_valid_after"], name="certificates_not_val_1d775d_idx"),
        ),
    ]

