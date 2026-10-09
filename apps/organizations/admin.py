from django.contrib import admin

from .models import AccountingOffice, ClientCompany, OfficeMembership


@admin.register(AccountingOffice)
class AccountingOfficeAdmin(admin.ModelAdmin):
    list_display = ("legal_name", "tax_identifier", "created_at")
    search_fields = ("legal_name", "tax_identifier")


@admin.register(ClientCompany)
class ClientCompanyAdmin(admin.ModelAdmin):
    list_display = (
        "legal_name",
        "tax_identifier",
        "state",
        "fiscal_environment",
        "status",
        "office",
    )
    list_filter = ("state", "fiscal_environment", "status")
    search_fields = ("legal_name", "tax_identifier")
    list_select_related = ("office",)


@admin.register(OfficeMembership)
class OfficeMembershipAdmin(admin.ModelAdmin):
    list_display = ("user", "office", "role", "is_active")
    list_filter = ("role", "is_active")
    search_fields = ("user__email", "office__legal_name", "office__tax_identifier")
    list_select_related = ("user", "office")
