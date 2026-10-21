from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("fiscal", "0015_nfce_wait_progress")]

    operations = [
        migrations.CreateModel(
            name="DownloadFileDeletion",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("path", models.CharField(max_length=1024)),
                (
                    "completed_at",
                    models.DateTimeField(blank=True, db_index=True, null=True),
                ),
                ("outcome", models.CharField(blank=True, max_length=24)),
                ("attempts", models.PositiveIntegerField(default=0)),
                (
                    "request",
                    models.ForeignKey(
                        on_delete=models.PROTECT,
                        related_name="file_deletions",
                        to="fiscal.downloadrequest",
                    ),
                ),
            ],
            options={
                "constraints": [
                    models.UniqueConstraint(
                        fields=("request", "path"), name="unique_atf_file_deletion"
                    )
                ]
            },
        ),
        migrations.AddField(
            model_name="downloadrequest",
            name="deleted_at",
            field=models.DateTimeField(blank=True, db_index=True, null=True),
        ),
        migrations.AlterField(
            model_name="downloadpart",
            name="status",
            field=models.CharField(
                choices=[
                    (state, state)
                    for state in (
                        "queued",
                        "submitting",
                        "waiting",
                        "ambiguous",
                        "downloading",
                        "validating",
                        "succeeded",
                        "empty",
                        "failed",
                        "cancelled",
                    )
                ],
                default="queued",
                max_length=16,
            ),
        ),
    ]
