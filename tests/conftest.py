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


@pytest.fixture
def lifecycle_admin(download_actor):
    from apps.organizations.models import OfficeMembership

    OfficeMembership.objects.filter(user=download_actor).update(role="admin")
    return download_actor


@pytest.fixture
def lifecycle_request(download_company, lifecycle_admin):
    from datetime import date

    from apps.fiscal.atf.types import Period
    from apps.fiscal.services.downloads import request_download

    return request_download(
        company_id=download_company.pk,
        period=Period(date(2024, 10, 1), date(2024, 10, 18)),
        formats=("xml", "txt"),
        actor_id=lifecycle_admin.pk,
        trigger="manual",
        dispatch=False,
    )
