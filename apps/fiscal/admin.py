from typing import Any

from django.contrib import admin

from apps.organizations.admin_access import InstallationAdminMixin, ReadOnlyOfficeAdmin

from .models import (
    ArchiveMember,
    AtfAccessLease,
    DownloadArchive,
    DownloadAttempt,
    DownloadPart,
    DownloadPolicy,
    DownloadRequest,
    FiscalEvent,
    InvoiceDocument,
    InvoiceXmlVersion,
    RemoteResultBinding,
    RemoteSubmissionBarrier,
)


class AtfReadOnlyAdmin(ReadOnlyOfficeAdmin):
    def get_readonly_fields(self, request: Any, obj: Any = None) -> Any:
        return tuple(field.name for field in self.model._meta.fields)


for _model, _lookup in (
    (DownloadPolicy, "company__office"),
    (DownloadRequest, "company__office"),
    (DownloadPart, "request__company__office"),
    (DownloadAttempt, "part__request__company__office"),
    (DownloadArchive, "part__request__company__office"),
    (ArchiveMember, "archive__part__request__company__office"),
    (InvoiceDocument, "company__office"),
    (InvoiceXmlVersion, "document__company__office"),
    (FiscalEvent, "company__office"),
    (RemoteResultBinding, "part__request__company__office"),
):
    admin.site.register(
        _model,
        type(
            f"{_model.__name__}Admin", (AtfReadOnlyAdmin,), {"office_lookup": _lookup}
        ),
    )


class AtfInstallationAdmin(InstallationAdminMixin, AtfReadOnlyAdmin):
    def get_queryset(self, request: Any) -> Any:
        queryset = admin.ModelAdmin.get_queryset(self, request)
        return queryset if request.user.is_superuser else queryset.none()

    def has_add_permission(self, request: Any) -> Any:
        return False

    def has_change_permission(self, request: Any, obj: Any = None) -> Any:
        return False

    def has_delete_permission(self, request: Any, obj: Any = None) -> Any:
        return False


for _infrastructure_model in (AtfAccessLease, RemoteSubmissionBarrier):
    admin.site.register(_infrastructure_model, AtfInstallationAdmin)
