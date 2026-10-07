from django.contrib import admin

from .models import AuditLog


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ("created_at", "action", "target", "actor", "correlation_id")
    list_filter = ("action",)
    search_fields = ("target", "action")
    readonly_fields = ("actor", "action", "target", "correlation_id", "payload", "created_at")

    def has_add_permission(self, request):  # type: ignore[no-untyped-def]
        return False

    def has_change_permission(self, request, obj=None):  # type: ignore[no-untyped-def]
        return False

