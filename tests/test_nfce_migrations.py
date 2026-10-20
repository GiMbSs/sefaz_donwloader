from datetime import date

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor


@pytest.mark.django_db(transaction=True)
def test_nfce_upgrade_preserves_existing_nfe_policy_and_request():
    executor = MigrationExecutor(connection)
    latest = executor.loader.graph.leaf_nodes()
    previous = [
        ("fiscal", "0013_retire_legacy_dfe"),
        ("organizations", "0006_retire_legacy_dfe"),
    ]
    try:
        executor.migrate(previous)
        registry = executor.loader.project_state(previous).apps
        office = registry.get_model("organizations", "AccountingOffice").objects.create(
            legal_name="Migration office", tax_identifier="00000000000191"
        )
        company = registry.get_model("organizations", "ClientCompany").objects.create(
            office_id=office.pk,
            legal_name="Migration company",
            tax_identifier="00000000000191",
        )
        policy = registry.get_model("fiscal", "DownloadPolicy").objects.create(
            company_id=company.pk, mode="automatic", is_active=True
        )
        request = registry.get_model("fiscal", "DownloadRequest").objects.create(
            company_id=company.pk,
            policy_id=policy.pk,
            start_date=date(2024, 10, 10),
            end_date=date(2024, 10, 10),
            active_key="legacy-nfe-request",
        )
        executor = MigrationExecutor(connection)
        executor.migrate(latest)
        upgraded = executor.loader.project_state(latest).apps
        saved_policy = upgraded.get_model("fiscal", "DownloadPolicy").objects.get(
            pk=policy.pk
        )
        saved_request = upgraded.get_model("fiscal", "DownloadRequest").objects.get(
            pk=request.pk
        )
        assert saved_policy.document_models == ["55"]
        assert saved_policy.is_active
        assert saved_request.document_model == "55"
        assert saved_request.active_key == "legacy-nfe-request"
    finally:
        MigrationExecutor(connection).migrate(latest)
