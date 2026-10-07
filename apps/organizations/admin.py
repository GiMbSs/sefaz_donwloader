from django.contrib import admin

from .models import AccountingOffice, ClientCompany


@admin.register(AccountingOffice)
class AccountingOfficeAdmin(admin.ModelAdmin):
    list_display = ("legal_name", "tax_identifier", "created_at")
    search_fields = ("legal_name", "tax_identifier")


@admin.register(ClientCompany)
class ClientCompanyAdmin(admin.ModelAdmin):
    list_display = ("legal_name", "tax_identifier", "state", "status", "office")
    list_filter = ("state", "status")
    search_fields = ("legal_name", "tax_identifier")
    list_select_related = ("office",)

