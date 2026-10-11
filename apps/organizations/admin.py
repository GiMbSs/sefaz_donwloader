from django.contrib import admin, messages
from django.contrib.admin import helpers
from django.db import transaction
from django.template.response import TemplateResponse

from apps.operations.models import AuditLog

from .admin_access import InstallationAdminMixin, OfficeScopedAdmin
from .models import AccountingOffice, ClientCompany, OfficeMembership


@admin.register(AccountingOffice)
class AccountingOfficeAdmin(InstallationAdminMixin, admin.ModelAdmin):
    list_display = ("legal_name", "tax_identifier", "created_at")
    search_fields = ("legal_name", "tax_identifier")


@admin.register(ClientCompany)
class ClientCompanyAdmin(OfficeScopedAdmin):
    office_lookup = "office"
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
    actions = ("promote_to_production",)

    @admin.action(
        description="Promover empresas selecionadas para Produção",
        permissions=("change",),
    )
    def promote_to_production(self, request, queryset):
        """Promote an explicit selection while keeping fiscal history intact."""

        companies = queryset.filter(
            fiscal_environment=ClientCompany.FiscalEnvironment.HOMOLOGATION
        )
        if not companies.exists():
            self.message_user(
                request,
                "Nenhuma empresa selecionada está em Homologação.",
                level=messages.WARNING,
            )
            return None

        if request.POST.get("confirm_promotion") != "yes":
            context = {
                **self.admin_site.each_context(request),
                "title": "Confirmar promoção para Produção",
                "companies": companies,
                "opts": self.model._meta,
                "action_checkbox_name": helpers.ACTION_CHECKBOX_NAME,
            }
            return TemplateResponse(
                request,
                "admin/organizations/clientcompany/promote_to_production.html",
                context,
            )

        company_ids = list(companies.values_list("pk", flat=True))
        promoted_count = 0
        with transaction.atomic():
            locked_companies = ClientCompany.objects.select_for_update().filter(
                pk__in=company_ids,
                fiscal_environment=ClientCompany.FiscalEnvironment.HOMOLOGATION,
            )
            for company in locked_companies:
                company.fiscal_environment = ClientCompany.FiscalEnvironment.PRODUCTION
                company.save(update_fields=("fiscal_environment", "updated_at"))
                AuditLog.objects.create(
                    actor=request.user,
                    action="organizations.fiscal_environment_promoted",
                    target=f"organizations.client_company:{company.pk}",
                    payload={
                        "from_environment": (
                            ClientCompany.FiscalEnvironment.HOMOLOGATION
                        ),
                        "to_environment": ClientCompany.FiscalEnvironment.PRODUCTION,
                        "source": "django_admin",
                    },
                )
                promoted_count += 1

        self.message_user(
            request,
            (
                f"{promoted_count} empresa(s) promovida(s) para Produção. "
                "O histórico de Homologação foi preservado."
            ),
            level=messages.SUCCESS,
        )
        return None


@admin.register(OfficeMembership)
class OfficeMembershipAdmin(InstallationAdminMixin, admin.ModelAdmin):
    list_display = ("user", "office", "role", "is_active")
    list_filter = ("role", "is_active")
    search_fields = ("user__email", "office__legal_name", "office__tax_identifier")
    list_select_related = ("user", "office")
