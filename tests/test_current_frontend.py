import pytest
from lxml import html

from apps.accounts.models import User
from apps.organizations.models import AccountingOffice, ClientCompany, OfficeMembership


@pytest.fixture
def current_frontend_user(client, db):
    office = AccountingOffice.objects.create(
        legal_name="Escritório de demonstração", tax_identifier="00000000000191"
    )
    user = User.objects.create_user(email="frontend@example.test")
    OfficeMembership.objects.create(office=office, user=user, role="admin")
    client.force_login(user)
    return office


def test_company_registration_does_not_require_retired_fiscal_controls(
    client, current_frontend_user
):
    response = client.get("/empresas/nova/")
    assert response.status_code == 200
    page = html.fromstring(response.content)
    fields = set(page.xpath("//form//*[@name]/@name"))
    assert not fields & {"initial_nsu", "fiscal_environment", "auto_correct_nsu"}
    response = client.post(
        "/empresas/nova/",
        {
            "office": current_frontend_user.pk,
            "legal_name": "Empresa de demonstração",
            "tax_identifier": "00000000000191",
            "state_registration": "",
            "state": "PB",
            "status": "active",
        },
    )
    assert response.status_code == 302
    assert ClientCompany.objects.filter(legal_name="Empresa de demonstração").exists()


def test_download_navigation_and_period_form_are_available(
    client, current_frontend_user
):
    company = ClientCompany.objects.create(
        office=current_frontend_user,
        legal_name="Empresa de demonstração",
        tax_identifier="00000000000191",
    )
    dashboard = client.get("/")
    navigation = html.fromstring(dashboard.content)
    assert navigation.xpath('//nav//a[@href="/downloads/"]')
    assert client.get("/downloads/").status_code == 200
    response = client.get(f"/empresas/{company.pk}/downloads/novo/")
    assert response.status_code == 200
    form = html.fromstring(response.content)
    assert form.xpath('//input[@name="start_date"][@type="date"][@required]')
    assert form.xpath('//input[@name="end_date"][@type="date"][@required]')
    assert form.xpath('//select[@name="document_model"]/option[@value="65"]')


def test_company_list_has_no_retired_environment_column(client, current_frontend_user):
    ClientCompany.objects.create(
        office=current_frontend_user,
        legal_name="Empresa de demonstração",
        tax_identifier="00000000000191",
    )
    response = client.get("/empresas/")
    assert response.status_code == 200
    page = html.fromstring(response.content)
    assert "Ambiente" not in page.xpath("//table/thead/tr/th/text()")


def test_dashboard_distinguishes_nfe_and_nfce_requests(client, current_frontend_user):
    from datetime import date

    from apps.fiscal.models import DownloadRequest

    company = ClientCompany.objects.create(
        office=current_frontend_user,
        legal_name="Empresa de demonstração",
        tax_identifier="00000000000191",
    )
    requests = [
        DownloadRequest.objects.create(
            company=company,
            start_date=date(2024, 10, 10),
            end_date=date(2024, 10, 10),
            document_model=model,
            active_key=f"frontend-{model}",
        )
        for model in ("55", "65")
    ]
    page = html.fromstring(client.get("/").content)
    for request, label in zip(requests, ("NF-e", "NFC-e"), strict=True):
        row = page.xpath(f'//tr[td/a[@href="/downloads/{request.pk}/"]]')
        assert len(row) == 1
        assert label in " ".join(row[0].itertext())
