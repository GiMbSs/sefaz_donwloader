"""Types for views whose dispatch enforces local authentication."""

from typing import TYPE_CHECKING, Any

from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpRequest
from django.views.generic import ListView

from apps.accounts.models import User


class AuthenticatedHttpRequest(HttpRequest):
    user: User


class AuthenticatedViewMixin(LoginRequiredMixin):
    # Django's View and TemplateResponseMixin declare this independently.
    request: Any
    kwargs: dict[str, Any]


if TYPE_CHECKING:
    TypedListView = ListView[Any]
else:
    TypedListView = ListView
