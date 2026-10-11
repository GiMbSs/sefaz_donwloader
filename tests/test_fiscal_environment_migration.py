import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor


@pytest.mark.django_db(transaction=True)
def test_environment_migration_preserves_legacy_paths_and_classifies_only_known_scope():
    executor = MigrationExecutor(connection)
    previous = [
        ("fiscal", "0006_sync_policy_recurrence"),
        ("organizations", "0005_company_lifecycle_and_environment"),
    ]
    current = [
        ("fiscal", "0007_document_environment"),
        ("organizations", "0005_company_lifecycle_and_environment"),
    ]
    executor.migrate(previous)
    try:
        apps = executor.loader.project_state(previous).apps
        Office = apps.get_model("organizations", "AccountingOffice")
        Company = apps.get_model("organizations", "ClientCompany")
        Document = apps.get_model("fiscal", "FiscalDocument")
        Control = apps.get_model("fiscal", "NsuControl")
        Batch = apps.get_model("fiscal", "DistributionBatch")
        Item = apps.get_model("fiscal", "DistributionItem")
        office = Office.objects.create(
            legal_name="Legacy", tax_identifier="00000000000191"
        )
        company = Company.objects.create(
            office=office, legal_name="Legacy", tax_identifier="00000000000191"
        )
        documents = []
        for index in range(3):
            documents.append(
                Document.objects.create(
                    company=company,
                    access_key=str(index).zfill(44),
                    model="55",
                    kind="summary",
                    schema_name="resNFe_v1.01.xsd",
                    document_root="resNFe",
                    xml_sha256=str(index).zfill(64),
                    xml_path=f"legacy/{index}.xml",
                )
            )
        for index, environment in enumerate(["production", "homologation"]):
            control = Control.objects.create(company=company, environment=environment)
            batch = Batch.objects.create(
                company=company,
                nsu_control=control,
                response_sha256=str(index).zfill(64),
                raw_response_path=f"legacy/batch{index}.xml",
                status_code="138",
            )
            for document in (
                [documents[0], documents[1]] if index == 0 else [documents[1]]
            ):
                Item.objects.create(
                    batch=batch,
                    fiscal_document=document,
                    nsu=str(document.pk).zfill(15),
                    schema_name="resNFe_v1.01.xsd",
                    compressed_sha256="a" * 64,
                    processing_status="stored",
                )
        executor = MigrationExecutor(connection)
        executor.migrate(current)
        Document = executor.loader.project_state(current).apps.get_model(
            "fiscal", "FiscalDocument"
        )
        migrated = list(Document.objects.filter(company_id=company.pk).order_by("pk"))
        assert [doc.environment for doc in migrated] == ["production", "", ""]
        assert [doc.xml_path for doc in migrated] == [
            f"legacy/{i}.xml" for i in range(3)
        ]
        assert [doc.pk for doc in migrated] == [doc.pk for doc in documents]
    finally:
        MigrationExecutor(connection).migrate(current)
