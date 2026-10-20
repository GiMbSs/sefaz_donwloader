from typing import TYPE_CHECKING, Any

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.models import Group

from apps.organizations.admin_access import InstallationAdminMixin, ModelAdminBase

from .models import User

if TYPE_CHECKING:
    UserAdminBase = UserAdmin[Any]
else:
    UserAdminBase = UserAdmin


@admin.register(User)
class LocalUserAdmin(InstallationAdminMixin, UserAdminBase):
    ordering = ("email",)
    list_display = ("email", "first_name", "last_name", "is_staff", "is_active")
    search_fields = ("email", "first_name", "last_name")
    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("Identificação", {"fields": ("first_name", "last_name")}),
        (
            "Permissões",
            {
                "fields": (
                    "is_active",
                    "is_staff",
                    "is_superuser",
                    "groups",
                    "user_permissions",
                )
            },
        ),
        ("Datas", {"fields": ("last_login", "date_joined")}),
    )
    add_fieldsets = (
        (None, {"classes": ("wide",), "fields": ("email", "password1", "password2")}),
    )


admin.site.unregister(Group)


@admin.register(Group)
class LocalGroupAdmin(InstallationAdminMixin, ModelAdminBase):
    search_fields = ("name",)
    filter_horizontal = ("permissions",)
