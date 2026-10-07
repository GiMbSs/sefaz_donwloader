import uuid

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
from django.db.models import Q


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("certificates", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="CertificateUpload",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("request_id", models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
                ("filename", models.CharField(max_length=255, verbose_name="nome original")),
                ("encrypted_payload", models.BinaryField(blank=True, editable=False, null=True)),
                ("encrypted_password", models.BinaryField(blank=True, editable=False, null=True)),
                ("status", models.CharField(choices=[("submitted", "Recebido"), ("processing", "Em processamento"), ("completed", "Concluído"), ("failed", "Falhou"), ("expired", "Expirado")], default="submitted", max_length=16, verbose_name="situação")),
                ("error_message", models.CharField(blank=True, max_length=255, verbose_name="erro")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("expires_at", models.DateTimeField()),
                ("started_at", models.DateTimeField(blank=True, null=True)),
                ("processed_at", models.DateTimeField(blank=True, null=True)),
                ("certificate", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="upload_requests", to="certificates.digitalcertificate")),
                ("company", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="certificate_uploads", to="organizations.clientcompany")),
                ("uploaded_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="certificate_upload_requests", to=settings.AUTH_USER_MODEL)),
            ],
            options={"verbose_name": "envio de certificado", "verbose_name_plural": "envios de certificados"},
        ),
        migrations.AddConstraint(
            model_name="certificateupload",
            constraint=models.UniqueConstraint(
                condition=Q(("status__in", ("submitted", "processing"))),
                fields=("company",),
                name="one_active_certificate_upload_per_company",
            ),
        ),
        migrations.AddIndex(
            model_name="certificateupload",
            index=models.Index(fields=["company", "status"], name="certificat_company_7b096c_idx"),
        ),
        migrations.AddIndex(
            model_name="certificateupload",
            index=models.Index(fields=["expires_at", "status"], name="certificat_expires_57b761_idx"),
        ),
    ]
