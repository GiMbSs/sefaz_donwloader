from django.contrib import admin

from .models import DistributionBatch, DistributionItem, FiscalDocument, NsuControl, SyncPolicy, SyncRequest


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


class DistributionItemInline(admin.TabularInline):
    model = DistributionItem
    extra = 0
    readonly_fields = (
        "nsu",
        "schema_name",
        "compressed_sha256",
        "xml_sha256",
        "fiscal_document",
        "processing_status",
        "processing_error",
        "created_at",
    )
    can_delete = False


@admin.register(DistributionBatch)
class DistributionBatchAdmin(admin.ModelAdmin):
    list_display = ("company", "status_code", "document_count", "processing_status", "created_at")
    list_filter = ("status_code", "processing_status")
    search_fields = ("company__legal_name", "company__tax_identifier", "response_sha256")
    list_select_related = ("company", "nsu_control", "sync_request")
    readonly_fields = (
        "company",
        "nsu_control",
        "sync_request",
        "response_sha256",
        "raw_response_path",
        "status_code",
        "reason",
        "response_at",
        "returned_last_nsu",
        "returned_max_nsu",
        "document_count",
        "processing_status",
        "processing_error",
        "created_at",
        "processed_at",
    )
    inlines = (DistributionItemInline,)

    def has_add_permission(self, request):  # type: ignore[no-untyped-def]
        return False

    def has_change_permission(self, request, obj=None):  # type: ignore[no-untyped-def]
        return False


@admin.register(FiscalDocument)
class FiscalDocumentAdmin(admin.ModelAdmin):
    list_display = ("company", "access_key", "model", "kind", "validation_status")
    list_filter = ("model", "kind", "validation_status")
    search_fields = ("company__legal_name", "company__tax_identifier", "access_key")
    list_select_related = ("company",)
    readonly_fields = (
        "company",
        "access_key",
        "model",
        "kind",
        "schema_name",
        "document_root",
        "xml_sha256",
        "xml_path",
        "validation_status",
        "validation_error",
        "first_received_at",
        "last_received_at",
    )

    def has_add_permission(self, request):  # type: ignore[no-untyped-def]
        return False

    def has_change_permission(self, request, obj=None):  # type: ignore[no-untyped-def]
        return False
