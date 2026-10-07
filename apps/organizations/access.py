"""Tenant-scoped access helpers for the accounting workstation."""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.db.models import QuerySet

from apps.organizations.models import AccountingOffice, ClientCompany, OfficeMembership

if TYPE_CHECKING:
    from apps.accounts.models import User


def accessible_companies(user: User) -> QuerySet[ClientCompany]:
    if user.is_superuser:
        return ClientCompany.objects.all()
    return ClientCompany.objects.filter(
        office__memberships__user=user,
        office__memberships__is_active=True,
    ).distinct()


def manageable_companies(user: User) -> QuerySet[ClientCompany]:
    if user.is_superuser:
        return ClientCompany.objects.all()
    return ClientCompany.objects.filter(
        office__memberships__user=user,
        office__memberships__is_active=True,
        office__memberships__role=OfficeMembership.Role.ADMIN,
    ).distinct()


def manageable_offices(user: User) -> QuerySet[AccountingOffice]:
    if user.is_superuser:
        return AccountingOffice.objects.all()
    return AccountingOffice.objects.filter(
        memberships__user=user,
        memberships__is_active=True,
        memberships__role=OfficeMembership.Role.ADMIN,
    )
