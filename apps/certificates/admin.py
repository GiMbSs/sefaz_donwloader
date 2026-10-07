from django.contrib import admin

from .models import DigitalCertificate


@admin.register(DigitalCertificate)
class DigitalCertificateAdmin(admin.ModelAdmin):
    list_display = (
        "company",
        "serial_number",
        "status",
        "not_valid_after",
        "created_at",
    )
    list_filter = ("status",)
    search_fields = ("company__legal_name", "company__tax_identifier", "serial_number")
    list_select_related = ("company", "uploaded_by")
    readonly_fields = (
        "storage_id",
        "encrypted_path",
        "content_sha256",
        "certificate_fingerprint_sha256",
        "serial_number",
        "subject",
        "issuer",
        "not_valid_before",
        "not_valid_after",
        "uploaded_by",
        "created_at",
        "replaced_at",
    )
    exclude = ("sealed_password",)

    def has_add_permission(self, request):  # type: ignore[no-untyped-def]
        return False

    def has_change_permission(self, request, obj=None):  # type: ignore[no-untyped-def]
        return False

