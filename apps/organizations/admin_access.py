"""Shared tenant boundaries for Django's technical administration."""

from django.contrib import admin

from .access import manageable_companies, manageable_offices
from .models import AccountingOffice, ClientCompany


class OfficeScopedAdmin(admin.ModelAdmin):
    office_lookup = "company__office"

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        if request.user.is_superuser:
            return queryset
        return queryset.filter(
            **{f"{self.office_lookup}__in": manageable_offices(request.user)}
        ).distinct()

    def has_view_permission(self, request, obj=None):
        allowed = super().has_view_permission(request, obj)
        return allowed and (
            obj is None or self.get_queryset(request).filter(pk=obj.pk).exists()
        )

    def has_change_permission(self, request, obj=None):
        allowed = super().has_change_permission(request, obj)
        return allowed and (
            obj is None or self.get_queryset(request).filter(pk=obj.pk).exists()
        )

    def has_delete_permission(self, request, obj=None):
        return False

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.remote_field.model is ClientCompany:
            kwargs["queryset"] = manageable_companies(request.user)
        elif db_field.remote_field.model is AccountingOffice:
            kwargs["queryset"] = manageable_offices(request.user)
        return super().formfield_for_foreignkey(db_field, request, **kwargs)


class ReadOnlyOfficeAdmin(OfficeScopedAdmin):
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


class InstallationAdminMixin:
    def has_module_permission(self, request):
        return request.user.is_superuser

    def has_view_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_add_permission(self, request):
        return request.user.is_superuser

    def has_change_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser
