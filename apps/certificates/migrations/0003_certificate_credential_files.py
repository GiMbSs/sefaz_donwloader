from django.contrib.auth.hashers import make_password
from django.db import migrations, models


def move_credentials_out_of_database(apps, schema_editor):
    """Move legacy reversible DB secrets into each client's private directory."""
    from apps.certificates.services.vault import CertificateVault

    certificate_model = apps.get_model("certificates", "DigitalCertificate")
    vault = CertificateVault()
    for certificate in certificate_model.objects.iterator():
        old_path = certificate.encrypted_path
        payload = vault.load_legacy(old_path, certificate.storage_id)
        password = vault.unseal_legacy_password(
            certificate.sealed_password,
            certificate.storage_id,
        )
        certificate.encrypted_path = vault.store_certificate(
            company_id=certificate.company_id,
            storage_id=certificate.storage_id,
            payload=payload,
        )
        certificate.encrypted_password_path = vault.store_password(
            company_id=certificate.company_id,
            storage_id=certificate.storage_id,
            password=password,
        )
        certificate.password_hash = make_password(password)
        certificate.save(
            update_fields=(
                "encrypted_path",
                "encrypted_password_path",
                "password_hash",
            )
        )
        vault.remove_legacy(old_path)


class Migration(migrations.Migration):
    dependencies = [("certificates", "0002_certificateupload")]

    operations = [
        migrations.AddField(
            model_name="digitalcertificate",
            name="encrypted_password_path",
            field=models.CharField(
                blank=True,
                editable=False,
                max_length=255,
                null=True,
                unique=True,
            ),
        ),
        migrations.AddField(
            model_name="digitalcertificate",
            name="password_hash",
            field=models.CharField(
                blank=True,
                editable=False,
                max_length=255,
                null=True,
            ),
        ),
        migrations.RunPython(move_credentials_out_of_database, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="digitalcertificate",
            name="encrypted_password_path",
            field=models.CharField(editable=False, max_length=255, unique=True),
        ),
        migrations.AlterField(
            model_name="digitalcertificate",
            name="password_hash",
            field=models.CharField(editable=False, max_length=255),
        ),
        migrations.RemoveField(
            model_name="digitalcertificate",
            name="sealed_password",
        ),
    ]
