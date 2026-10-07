from datetime import time

import pytest

from apps.fiscal.models import NsuControl, SyncPolicy
from apps.organizations.models import AccountingOffice, ClientCompany


@pytest.mark.django_db
def test_company_has_one_policy_and_independent_nsu_by_environment():
    office = AccountingOffice.objects.create(
        legal_name="Contabilidade Exemplo Ltda.", tax_identifier="00000000000191"
    )
    company = ClientCompany.objects.create(
        office=office,
        legal_name="Cliente Exemplo Ltda.",
        tax_identifier="00000000000191",
    )
    policy = SyncPolicy.objects.create(company=company, scheduled_time=time(2, 0))
    production = NsuControl.objects.create(
        company=company,
        environment=NsuControl.Environment.PRODUCTION,
        last_nsu="000000000000001",
    )
    homologation = NsuControl.objects.create(
        company=company,
        environment=NsuControl.Environment.HOMOLOGATION,
        last_nsu="000000000000000",
    )

    assert policy.mode == SyncPolicy.Mode.DAILY
    assert production.pk != homologation.pk
