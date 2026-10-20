from django.contrib import admin

from apps.organizations.admin_access import ModelAdminBase

from .admin_access import InstallationAdminMixin, OfficeScopedAdmin
from .models import AccountingOffice, ClientCompany, OfficeMembership


@admin.register(AccountingOffice)
class AccountingOfficeAdmin(InstallationAdminMixin, ModelAdminBase):
    list_display = ("legal_name", "tax_identifier", "created_at")
    search_fields = ("legal_name", "tax_identifier")


@admin.register(ClientCompany)
class ClientCompanyAdmin(OfficeScopedAdmin):
    office_lookup = "office"
    list_display = (
        "legal_name",
        "tax_identifier",
        "state",
        "status",
        "office",
    )
    list_filter = ("state", "status")
    search_fields = ("legal_name", "tax_identifier")
    list_select_related = ("office",)
    actions = ()


@admin.register(OfficeMembership)
class OfficeMembershipAdmin(InstallationAdminMixin, ModelAdminBase):
    list_display = ("user", "office", "role", "is_active")
    list_filter = ("role", "is_active")
    search_fields = ("user__email", "office__legal_name", "office__tax_identifier")
    list_select_related = ("user", "office")
