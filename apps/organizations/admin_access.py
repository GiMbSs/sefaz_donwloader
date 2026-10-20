"""Shared tenant boundaries for Django's technical administration."""

from typing import TYPE_CHECKING, Any

from django.contrib import admin

from .access import manageable_companies, manageable_offices
from .models import AccountingOffice, ClientCompany

if TYPE_CHECKING:
    ModelAdminBase = admin.ModelAdmin[Any]
else:
    ModelAdminBase = admin.ModelAdmin


class OfficeScopedAdmin(ModelAdminBase):
    office_lookup = "company__office"

    def get_queryset(self, request: Any) -> Any:
        queryset = super().get_queryset(request)
        if request.user.is_superuser:
            return queryset
        return queryset.filter(
            **{f"{self.office_lookup}__in": manageable_offices(request.user)}
        ).distinct()

    def has_view_permission(self, request: Any, obj: Any = None) -> Any:
        allowed = super().has_view_permission(request, obj)
        return allowed and (
            obj is None or self.get_queryset(request).filter(pk=obj.pk).exists()
        )

    def has_change_permission(self, request: Any, obj: Any = None) -> Any:
        allowed = super().has_change_permission(request, obj)
        return allowed and (
            obj is None or self.get_queryset(request).filter(pk=obj.pk).exists()
        )

    def has_delete_permission(self, request: Any, obj: Any = None) -> Any:
        return False

    def formfield_for_foreignkey(
        self, db_field: Any, request: Any, **kwargs: Any
    ) -> Any:
        if db_field.remote_field.model is ClientCompany:
            kwargs["queryset"] = manageable_companies(request.user)
        elif db_field.remote_field.model is AccountingOffice:
            kwargs["queryset"] = manageable_offices(request.user)
        return super().formfield_for_foreignkey(db_field, request, **kwargs)


class ReadOnlyOfficeAdmin(OfficeScopedAdmin):
    def has_add_permission(self, request: Any) -> Any:
        return False

    def has_change_permission(self, request: Any, obj: Any = None) -> Any:
        return False


class InstallationAdminMixin:
    def has_module_permission(self, request: Any) -> Any:
        return request.user.is_superuser

    def has_view_permission(self, request: Any, obj: Any = None) -> Any:
        return request.user.is_superuser

    def has_add_permission(self, request: Any) -> Any:
        return request.user.is_superuser

    def has_change_permission(self, request: Any, obj: Any = None) -> Any:
        return request.user.is_superuser

    def has_delete_permission(self, request: Any, obj: Any = None) -> Any:
        return request.user.is_superuser
