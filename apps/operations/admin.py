from django.contrib import admin

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


@admin.register(OperationAlert)
class OperationAlertAdmin(admin.ModelAdmin):
    list_display = ("created_at", "company", "severity", "status", "title")
    list_filter = ("severity", "status")
    search_fields = ("company__legal_name", "company__tax_identifier", "title", "code")
    list_select_related = ("company", "resolved_by")
    readonly_fields = ("company", "code", "context", "created_at", "updated_at")
