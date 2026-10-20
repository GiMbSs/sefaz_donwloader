import pytest
from django.contrib import admin
from django.contrib.auth.models import Permission
from django.test import RequestFactory

from apps.accounts.models import User
from apps.fiscal.models import DownloadPolicy, DownloadRequest
from apps.operations.models import AuditLog
from apps.organizations.models import AccountingOffice, ClientCompany, OfficeMembership


@pytest.mark.django_db
def test_admin_company_scope_and_foreign_key_choices_are_tenant_scoped():
    user = User.objects.create_user(
        email="tenant@example.test", password="test", is_staff=True
    )
    office = AccountingOffice.objects.create(
        legal_name="Office A", tax_identifier="00000000000191"
    )
    other = AccountingOffice.objects.create(
        legal_name="Office B", tax_identifier="00000000E08G12"
    )
    visible = ClientCompany.objects.create(
        office=office, legal_name="Visible", tax_identifier="00000000000191"
    )
    hidden = ClientCompany.objects.create(
        office=other, legal_name="Hidden", tax_identifier="00000000000191"
    )
    OfficeMembership.objects.create(office=office, user=user, role="admin")
    user.user_permissions.add(Permission.objects.get(codename="change_clientcompany"))
    request = RequestFactory().get("/admin/")
    request.user = user
    model_admin = admin.site._registry[ClientCompany]
    assert list(model_admin.get_queryset(request)) == [visible]
    assert not model_admin.has_change_permission(request, hidden)
    choices = model_admin.formfield_for_foreignkey(
        ClientCompany._meta.get_field("office"), request
    )
    assert list(choices.queryset) == [office]
    assert not model_admin.has_delete_permission(request, visible)
    for company in [visible, hidden]:
        DownloadPolicy.objects.create(company=company)
        AuditLog.objects.create(
            action="test", target=f"organizations.client_company:{company.pk}"
        )
        AuditLog.objects.create(
            action="test.payload",
            target="fiscal.sync_request:1",
            payload={"company_id": company.pk},
        )
    assert admin.site._registry[DownloadPolicy].get_queryset(request).count() == 1
    assert admin.site._registry[AuditLog].get_queryset(request).count() == 2
    assert not admin.site._registry[AuditLog].has_delete_permission(request)
    assert not admin.site._registry[DownloadRequest].has_add_permission(request)
    assert not admin.site._registry[DownloadRequest].has_change_permission(request)
    assert not admin.site._registry[User].has_change_permission(request)


@pytest.mark.django_db
def test_staff_without_office_membership_has_no_company_access():
    user = User.objects.create_user(
        email="unscoped@example.test", password="test", is_staff=True
    )
    office = AccountingOffice.objects.create(
        legal_name="Office", tax_identifier="00000000000191"
    )
    ClientCompany.objects.create(
        office=office, legal_name="Hidden", tax_identifier="00000000000191"
    )
    request = RequestFactory().get("/admin/")
    request.user = user
    assert not admin.site._registry[ClientCompany].get_queryset(request).exists()
