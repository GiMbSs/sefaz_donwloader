import pytest
from django.apps import apps


def test_only_atf_fiscal_models_are_registered():
    names = {model.__name__ for model in apps.get_app_config("fiscal").get_models()}
    assert {"DownloadRequest", "DownloadPolicy", "InvoiceDocument"} <= names
    assert not names & {
        "SyncPolicy",
        "SyncRequest",
        "NsuControl",
        "FiscalDocument",
        "DistributionBatch",
        "DistributionItem",
        "LegacyFiscalRecord",
        "LegacyMigrationRun",
    }


@pytest.mark.django_db(transaction=True)
def test_cutover_keeps_company_and_adapted_schedule_but_drops_old_tables(legacy_schema):
    from datetime import time

    from django.db import connection
    from django.db.migrations.executor import MigrationExecutor

    office = legacy_schema.get_model(
        "organizations", "AccountingOffice"
    ).objects.create(legal_name="Migration office", tax_identifier="00000000000191")
    company = legacy_schema.get_model("organizations", "ClientCompany").objects.create(
        office_id=office.pk,
        legal_name="Migration company",
        tax_identifier="00000000000191",
    )
    legacy_schema.get_model("fiscal", "SyncPolicy").objects.create(
        company_id=company.pk,
        mode="automatic",
        is_active=True,
        scheduled_time=time(3),
    )
    legacy_schema.get_model("fiscal", "NsuControl").objects.create(
        company_id=company.pk, environment="production", last_nsu="123"
    )
    executor = MigrationExecutor(connection)
    executor.migrate(executor.loader.graph.leaf_nodes())
    from apps.fiscal.models import DownloadPolicy
    from apps.organizations.models import ClientCompany

    assert ClientCompany.objects.filter(pk=company.pk).exists()
    policy = DownloadPolicy.objects.get(company_id=company.pk)
    assert policy.is_active and policy.scheduled_time == time(3)
    assert "fiscal_nsucontrol" not in connection.introspection.table_names()
    assert "fiscal_environment" not in {f.name for f in ClientCompany._meta.fields}
