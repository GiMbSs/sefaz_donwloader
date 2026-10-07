from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("organizations", "0002_cnpj_validators"),
    ]

    operations = [
        migrations.CreateModel(
            name="OfficeMembership",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("role", models.CharField(choices=[("admin", "Administrador"), ("operator", "Operador")], default="operator", max_length=16, verbose_name="perfil")),
                ("is_active", models.BooleanField(default=True, verbose_name="ativa")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="criada em")),
                ("office", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="memberships", to="organizations.accountingoffice")),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="office_memberships", to=settings.AUTH_USER_MODEL)),
            ],
            options={"verbose_name": "vínculo com escritório", "verbose_name_plural": "vínculos com escritórios"},
        ),
        migrations.AddConstraint(
            model_name="officemembership",
            constraint=models.UniqueConstraint(fields=("office", "user"), name="unique_office_membership_per_user"),
        ),
        migrations.AddIndex(
            model_name="officemembership",
            index=models.Index(fields=["user", "is_active"], name="organizatio_user_id_20db6c_idx"),
        ),
    ]
