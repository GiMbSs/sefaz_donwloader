from django.contrib import admin
from django.db.models import CharField, Q, Value
from django.db.models.fields.json import KeyTextTransform
from django.db.models.functions import Cast, Concat

from apps.organizations.access import manageable_companies, manageable_offices
from apps.organizations.admin_access import ReadOnlyOfficeAdmin

from .models import AuditLog, OperationAlert


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ("created_at", "action", "target", "actor", "correlation_id")
    list_filter = ("action",)
    search_fields = ("target", "action")
    readonly_fields = (
        "actor",
        "action",
        "target",
        "correlation_id",
        "payload",
        "created_at",
    )

    def has_add_permission(self, request):  # type: ignore[no-untyped-def]
        return False

    def has_change_permission(self, request, obj=None):  # type: ignore[no-untyped-def]
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        if request.user.is_superuser:
            return queryset
        companies = manageable_companies(request.user)
        offices = manageable_offices(request.user)
        company_targets = companies.annotate(
            audit_target=Concat(
                Value("organizations.client_company:"), Cast("pk", CharField())
            )
        ).values("audit_target")
        office_targets = offices.annotate(
            audit_target=Concat(
                Value("organizations.accounting_office:"), Cast("pk", CharField())
            )
        ).values("audit_target")
        company_ids = companies.annotate(scope_id=Cast("pk", CharField())).values(
            "scope_id"
        )
        office_ids = offices.annotate(scope_id=Cast("pk", CharField())).values(
            "scope_id"
        )
        return queryset.annotate(
            scope_company=KeyTextTransform("company_id", "payload"),
            scope_office=KeyTextTransform("office_id", "payload"),
        ).filter(
            Q(scope_company__in=company_ids)
            | Q(scope_office__in=office_ids)
            | Q(target__in=company_targets)
            | Q(target__in=office_targets)
        )


@admin.register(OperationAlert)
class OperationAlertAdmin(ReadOnlyOfficeAdmin):
    list_display = ("created_at", "company", "severity", "status", "title")
    list_filter = ("severity", "status")
    search_fields = ("company__legal_name", "company__tax_identifier", "title", "code")
    list_select_related = ("company", "resolved_by")
    readonly_fields = ("company", "code", "context", "created_at", "updated_at")
