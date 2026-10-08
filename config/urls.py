from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import path

from apps.operations import views

urlpatterns = [
    path("", views.DashboardView.as_view(), name="dashboard"),
    path("health/", views.health, name="health"),
    path(
        "entrar/",
        auth_views.LoginView.as_view(
            template_name="registration/login.html",
            redirect_authenticated_user=True,
        ),
        name="login",
    ),
    path("sair/", auth_views.LogoutView.as_view(), name="logout"),
    path("empresas/", views.CompanyListView.as_view(), name="company-list"),
    path("empresas/nova/", views.CompanyCreateView.as_view(), name="company-create"),
    path(
        "empresas/<int:company_id>/",
        views.CompanyDetailView.as_view(),
        name="company-detail",
    ),
    path(
        "empresas/<int:company_id>/editar/",
        views.CompanyUpdateView.as_view(),
        name="company-update",
    ),
    path(
        "empresas/<int:company_id>/politica/",
        views.CompanyPolicyUpdateView.as_view(),
        name="company-policy",
    ),
    path(
        "empresas/<int:company_id>/certificado/",
        views.CompanyCertificateUploadView.as_view(),
        name="company-certificate-upload",
    ),
    path(
        "empresas/<int:company_id>/sincronizar/",
        views.ManualSyncRequestView.as_view(),
        name="company-sync",
    ),
    path(
        "empresas/<int:company_id>/lotes/<int:batch_id>/reprocessar/",
        views.DistributionBatchReprocessView.as_view(),
        name="batch-reprocess",
    ),
    path("documentos/", views.FiscalDocumentListView.as_view(), name="document-list"),
    path(
        "documentos/<int:document_id>/xml/",
        views.FiscalDocumentDownloadView.as_view(),
        name="document-download",
    ),
    path("alertas/", views.OperationAlertListView.as_view(), name="alert-list"),
    path(
        "alertas/<int:alert_id>/resolver/",
        views.OperationAlertResolveView.as_view(),
        name="alert-resolve",
    ),
    path("admin/", admin.site.urls),
]
