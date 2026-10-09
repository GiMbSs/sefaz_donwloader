import pytest
from django.core.exceptions import ValidationError

from apps.operations.forms import ClientCompanyForm
from apps.organizations.models import AccountingOffice, ClientCompany
from apps.organizations.validators import (
    normalize_tax_identifier,
    validate_tax_identifier,
)


def test_accepts_official_alphanumeric_cnpj_shape_and_check_digits():
    value = "00.000.000/E08G-12"

    validate_tax_identifier(value)

    assert normalize_tax_identifier(value) == "00000000E08G12"


def test_rejects_cnpj_with_invalid_check_digits():
    with pytest.raises(ValidationError):
        validate_tax_identifier("00.000.000/E08G-13")


@pytest.mark.django_db
def test_company_full_clean_normalizes_formatted_cnpj():
    office = AccountingOffice(
        legal_name="Contabilidade Exemplo",
        tax_identifier="00.000.000/0001-91",
    )
    office.full_clean()
    office.save()
    company = ClientCompany(
        office=office,
        legal_name="Cliente Exemplo",
        tax_identifier="00.000.000/E08G-12",
    )

    company.full_clean()

    assert office.tax_identifier == "00000000000191"
    assert company.tax_identifier == "00000000E08G12"


@pytest.mark.django_db
def test_company_form_accepts_and_normalizes_a_formatted_cnpj():
    office = AccountingOffice.objects.create(
        legal_name="Contabilidade Exemplo",
        tax_identifier="00000000000191",
    )
    form = ClientCompanyForm(
        data={
            "office": office.pk,
            "legal_name": "Cliente Exemplo",
            "tax_identifier": "00.000.000/E08G-12",
            "state_registration": "",
            "state": "PB",
            "status": ClientCompany.Status.ACTIVE,
        },
        offices=AccountingOffice.objects.filter(pk=office.pk),
    )

    assert form.is_valid(), form.errors
    assert form.instance.tax_identifier == "00000000E08G12"
