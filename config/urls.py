from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import path

from apps.operations import download_views, views

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
    path(
        "escritorios/novo/",
        views.OfficeCreateView.as_view(),
        name="office-create",
    ),
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
        "empresas/<int:company_id>/excluir/",
        views.CompanyArchiveView.as_view(),
        name="company-archive",
    ),
    path(
        "empresas/<int:company_id>/politica/",
        views.CompanyPolicyUpdateView.as_view(),
        name="company-policy",
    ),
    path(
        "empresas/<int:company_id>/nsu/",
        download_views.retired_fiscal_endpoint,
    ),
    path(
        "empresas/<int:company_id>/nsu-inicial/",
        download_views.retired_fiscal_endpoint,
    ),
    path(
        "empresas/<int:company_id>/certificado/",
        views.CompanyCertificateUploadView.as_view(),
        name="company-certificate-upload",
    ),
    path(
        "empresas/<int:company_id>/sincronizar/",
        download_views.retired_fiscal_endpoint,
    ),
    path(
        "empresas/<int:company_id>/lotes/<int:batch_id>/reprocessar/",
        download_views.retired_fiscal_endpoint,
    ),
    path(
        "empresas/<int:company_id>/downloads/novo/",
        download_views.DownloadRequestCreateView.as_view(),
        name="company-download-create",
    ),
    path(
        "empresas/<int:company_id>/downloads/",
        download_views.DownloadRequestListView.as_view(),
        name="company-download-list",
    ),
    path(
        "downloads/",
        download_views.DownloadRequestListView.as_view(),
        name="download-request-list",
    ),
    path(
        "downloads/<uuid:request_id>/",
        download_views.DownloadRequestDetailView.as_view(),
        name="download-request-detail",
    ),
    path(
        "downloads/<uuid:request_id>/retomar/",
        download_views.DownloadRequestRecoverView.as_view(),
        name="download-request-recover",
    ),
    path(
        "downloads/arquivos/<uuid:archive_id>/",
        download_views.DownloadArchiveView.as_view(),
        name="download-archive",
    ),
    path(
        "downloads/arquivos/<uuid:archive_id>/revalidar/",
        download_views.DownloadArchiveRevalidateView.as_view(),
        name="download-archive-revalidate",
    ),
    path(
        "downloads/partes/<uuid:part_id>/conferir/",
        download_views.RemoteResultResolutionView.as_view(),
        name="download-result-resolve",
    ),
    path(
        "documentos/",
        download_views.InvoiceDocumentListView.as_view(),
        name="document-list",
    ),
    path(
        "notas/<int:document_id>/xml/",
        download_views.InvoiceXmlDownloadView.as_view(),
        name="invoice-xml-download",
    ),
    path(
        "eventos/<int:event_id>/xml/",
        download_views.EventXmlDownloadView.as_view(),
        name="event-xml-download",
    ),
    path(
        "relatorios/<int:member_id>/txt/",
        download_views.ArchiveMemberDownloadView.as_view(),
        name="archive-member-download",
    ),
    path(
        "documentos/<int:document_id>/xml/",
        download_views.retired_fiscal_endpoint,
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
