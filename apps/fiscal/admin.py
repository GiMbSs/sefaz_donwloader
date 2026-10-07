from django.contrib import admin

from .models import NsuControl, SyncPolicy, SyncRequest


@admin.register(SyncPolicy)
class SyncPolicyAdmin(admin.ModelAdmin):
    list_display = ("company", "mode", "scheduled_time", "is_active", "last_finished_at")
    list_filter = ("mode", "is_active")
    search_fields = ("company__legal_name", "company__tax_identifier")
    list_select_related = ("company",)


@admin.register(NsuControl)
class NsuControlAdmin(admin.ModelAdmin):
    list_display = ("company", "environment", "last_nsu", "maximum_nsu", "next_allowed_at")
    list_filter = ("environment", "service")
    search_fields = ("company__legal_name", "company__tax_identifier")
    list_select_related = ("company",)
    readonly_fields = ("last_nsu", "maximum_nsu", "next_allowed_at", "last_status_code", "updated_at")


@admin.register(SyncRequest)
class SyncRequestAdmin(admin.ModelAdmin):
    list_display = ("company", "environment", "trigger", "status", "requested_at")
    list_filter = ("environment", "trigger", "status")
    search_fields = ("company__legal_name", "company__tax_identifier")
    list_select_related = ("company", "requested_by")
    readonly_fields = ("requested_at", "started_at", "finished_at")

