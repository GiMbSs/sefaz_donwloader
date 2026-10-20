import pytest

from tests.test_certificate_reconciliation import binding  # noqa: F401
from tests.test_download_models import download_company as company_fixture

download_company = company_fixture


@pytest.fixture
def download_actor(download_company):
    from django.contrib.auth import get_user_model

    from apps.organizations.models import OfficeMembership

    user = get_user_model().objects.create_user(email="download@example.test")
    OfficeMembership.objects.create(
        office=download_company.office, user=user, role="operator"
    )
    return user


@pytest.fixture
def legacy_schema(transactional_db):
    """Rehearse upgrade only in a disposable test database."""
    from django.db import connection
    from django.db.migrations.executor import MigrationExecutor

    targets = [
        ("fiscal", "0009_atf_download_domain"),
        ("organizations", "0005_company_lifecycle_and_environment"),
    ]
    executor = MigrationExecutor(connection)
    executor.migrate(targets)
    registry = executor.loader.project_state(targets).apps
    try:
        yield registry
    finally:
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())
