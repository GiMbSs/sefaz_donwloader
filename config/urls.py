from django.contrib import admin
from django.urls import path

from apps.operations import views

urlpatterns = [
    path("", views.home, name="home"),
    path("health/", views.health, name="health"),
    path("admin/", admin.site.urls),
]

