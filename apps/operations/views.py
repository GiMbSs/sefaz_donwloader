"""Authenticated views for the accounting workstation."""

from __future__ import annotations

from datetime import time, timedelta
from typing import Any

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Q, QuerySet
from django.http import FileResponse, Http404, HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views import View
from django.views.generic import ListView, TemplateView

from apps.certificates.models import DigitalCertificate
from apps.certificates.services.uploads import (
    CertificateUploadError,
    stage_certificate_upload,
)
from apps.fiscal.models import FiscalDocument, NsuControl, SyncPolicy, SyncRequest
from apps.fiscal.services.storage import FiscalStorage, FiscalStorageError
from apps.fiscal.services.sync import (
    SynchronizationRequestError,
    request_synchronization,
)
from apps.operations.forms import (
    CertificateUploadForm,
    ClientCompanyForm,
    ManualSyncRequestForm,
    SyncPolicyForm,
)
from apps.operations.models import AuditLog
from apps.organizations.access import (
    accessible_companies,
    manageable_companies,
    manageable_offices,
)
from apps.organizations.models import ClientCompany


def health(request: HttpRequest) -> JsonResponse:
    """Minimal readiness endpoint that verifies database reachability."""
    from django.db import DatabaseError, connection

    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except DatabaseError:
        return JsonResponse({"status": "unavailable"}, status=503)
    return JsonResponse({"status": "ok"})


class DashboardView(LoginRequiredMixin, TemplateView):
    template_name = "operations/dashboard.html"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        companies = accessible_companies(self.request.user)
        active_company_ids = companies.filter(
            status=ClientCompany.Status.ACTIVE
        ).values("pk")
        expiry_limit = timezone.now() + timedelta(days=30)
        context.update(
            {
                "company_count": companies.count(),
                "active_company_count": active_company_ids.count(),
                "blocked_controls": NsuControl.objects.filter(
                    company_id__in=active_company_ids,
                    next_allowed_at__gt=timezone.now(),
                ).select_related("company"),
                "expiring_certificates": DigitalCertificate.objects.filter(
                    company_id__in=active_company_ids,
                    status=DigitalCertificate.Status.ACTIVE,
                    not_valid_after__lte=expiry_limit,
                ).select_related("company"),
                "recent_requests": SyncRequest.objects.filter(
                    company_id__in=active_company_ids
                )
                .select_related("company", "requested_by")
                .order_by("-requested_at")[:8],
            }
        )
        return context


class CompanyListView(LoginRequiredMixin, ListView):
    template_name = "operations/company_list.html"
    context_object_name = "companies"
    paginate_by = 25

    def get_queryset(self) -> QuerySet[ClientCompany]:
        queryset = accessible_companies(self.request.user).select_related("office")
        term = self.request.GET.get("q", "").strip()
        status = self.request.GET.get("status", "").strip()
        if term:
            queryset = queryset.filter(
                Q(legal_name__icontains=term) | Q(tax_identifier__icontains=term)
            )
        if status in ClientCompany.Status.values:
            queryset = queryset.filter(status=status)
        return queryset.order_by("legal_name")

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        context["can_create_company"] = manageable_offices(self.request.user).exists()
        context["selected_status"] = self.request.GET.get("status", "")
        context["query"] = self.request.GET.get("q", "")
        context["status_choices"] = ClientCompany.Status.choices
        return context


class CompanyAccessMixin(LoginRequiredMixin):
    manage_required = False

    def get_company(self) -> ClientCompany:
        queryset = (
            manageable_companies(self.request.user)
            if self.manage_required
            else accessible_companies(self.request.user)
        )
        return get_object_or_404(
            queryset.select_related("office"),
            pk=self.kwargs["company_id"],
        )


class CompanyDetailView(CompanyAccessMixin, TemplateView):
    template_name = "operations/company_detail.html"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        company = self.get_company()
        context.update(
            {
                "company": company,
                "policy": getattr(company, "sync_policy", None),
                "active_certificate": company.digital_certificates.filter(
                    status=DigitalCertificate.Status.ACTIVE
                ).first(),
                "latest_certificate_upload": company.certificate_uploads.order_by(
                    "-created_at"
                ).first(),
                "nsu_controls": company.nsu_controls.order_by("environment", "service"),
                "sync_requests": company.sync_requests.select_related(
                    "requested_by"
                ).order_by("-requested_at")[:12],
                "documents": company.fiscal_documents.order_by(
                    "-last_received_at"
                )[:12],
                "manual_sync_form": ManualSyncRequestForm(),
                "can_manage": manageable_companies(self.request.user)
                .filter(pk=company.pk)
                .exists(),
            }
        )
        return context


class CompanyCreateView(LoginRequiredMixin, View):
    template_name = "operations/company_form.html"

    def _offices(self):
        return manageable_offices(self.request.user)

    def get(self, request: HttpRequest) -> HttpResponse:
        offices = self._offices()
        if not offices.exists():
            raise PermissionDenied("Seu perfil não administra nenhum escritório.")
        return render(
            request,
            self.template_name,
            {"form": ClientCompanyForm(offices=offices), "is_create": True},
        )

    def post(self, request: HttpRequest) -> HttpResponse:
        offices = self._offices()
        if not offices.exists():
            raise PermissionDenied("Seu perfil não administra nenhum escritório.")
        form = ClientCompanyForm(request.POST, offices=offices)
        if not form.is_valid():
            return render(
                request,
                self.template_name,
                {"form": form, "is_create": True},
                status=400,
            )
        with transaction.atomic():
            company = form.save()
            SyncPolicy.objects.create(
                company=company,
                mode=SyncPolicy.Mode.HYBRID,
                scheduled_time=time(2, 0),
            )
            AuditLog.objects.create(
                actor=request.user,
                action="organizations.company_created",
                target=f"organizations.client_company:{company.pk}",
                payload={"office_id": company.office_id},
            )
        messages.success(
            request,
            "Empresa cadastrada. Configure a política e o certificado antes da "
            "primeira consulta.",
        )
        return redirect("company-detail", company_id=company.pk)


class CompanyUpdateView(CompanyAccessMixin, View):
    template_name = "operations/company_form.html"
    manage_required = True

    def get(self, request: HttpRequest, company_id: int) -> HttpResponse:
        company = self.get_company()
        return render(
            request,
            self.template_name,
            {
                "form": ClientCompanyForm(
                    instance=company,
                    offices=manageable_offices(request.user),
                ),
                "company": company,
            },
        )

    def post(self, request: HttpRequest, company_id: int) -> HttpResponse:
        company = self.get_company()
        form = ClientCompanyForm(
            request.POST,
            instance=company,
            offices=manageable_offices(request.user),
        )
        if not form.is_valid():
            return render(
                request,
                self.template_name,
                {"form": form, "company": company},
                status=400,
            )
        with transaction.atomic():
            company = form.save()
            AuditLog.objects.create(
                actor=request.user,
                action="organizations.company_updated",
                target=f"organizations.client_company:{company.pk}",
                payload={"office_id": company.office_id},
            )
        messages.success(request, "Cadastro da empresa atualizado.")
        return redirect("company-detail", company_id=company.pk)


class CompanyPolicyUpdateView(CompanyAccessMixin, View):
    template_name = "operations/policy_form.html"
    manage_required = True

    def get_policy(self) -> SyncPolicy:
        company = self.get_company()
        policy, _ = SyncPolicy.objects.get_or_create(
            company=company,
            defaults={"mode": SyncPolicy.Mode.HYBRID, "scheduled_time": time(2, 0)},
        )
        return policy

    def get(self, request: HttpRequest, company_id: int) -> HttpResponse:
        policy = self.get_policy()
        return render(
            request,
            self.template_name,
            {"form": SyncPolicyForm(instance=policy), "company": policy.company},
        )

    def post(self, request: HttpRequest, company_id: int) -> HttpResponse:
        policy = self.get_policy()
        form = SyncPolicyForm(request.POST, instance=policy)
        if not form.is_valid():
            return render(
                request,
                self.template_name,
                {"form": form, "company": policy.company},
                status=400,
            )
        with transaction.atomic():
            policy = form.save()
            AuditLog.objects.create(
                actor=request.user,
                action="fiscal.sync_policy_updated",
                target=f"fiscal.sync_policy:{policy.pk}",
                payload={
                    "company_id": policy.company_id,
                    "mode": policy.mode,
                    "is_active": policy.is_active,
                },
            )
        messages.success(request, "Política de sincronização atualizada.")
        return redirect("company-detail", company_id=policy.company_id)


class CompanyCertificateUploadView(CompanyAccessMixin, View):
    template_name = "operations/certificate_upload.html"
    manage_required = True

    def get(self, request: HttpRequest, company_id: int) -> HttpResponse:
        company = self.get_company()
        return render(
            request,
            self.template_name,
            {
                "company": company,
                "form": CertificateUploadForm(),
                "latest_upload": company.certificate_uploads.order_by(
                    "-created_at"
                ).first(),
            },
        )

    def post(self, request: HttpRequest, company_id: int) -> HttpResponse:
        company = self.get_company()
        form = CertificateUploadForm(request.POST, request.FILES)
        if not form.is_valid():
            return render(
                request,
                self.template_name,
                {
                    "company": company,
                    "form": form,
                    "latest_upload": company.certificate_uploads.order_by(
                        "-created_at"
                    ).first(),
                },
                status=400,
            )
        certificate_file = form.cleaned_data["certificate_file"]
        try:
            result = stage_certificate_upload(
                company_id=company.pk,
                filename=certificate_file.name,
                payload=certificate_file.read(),
                password=form.cleaned_data["password"],
                uploaded_by=request.user,
            )
        except CertificateUploadError as error:
            messages.error(request, str(error))
        else:
            if result.created:
                messages.success(
                    request,
                    "Certificado recebido para processamento seguro pelo worker.",
                )
            else:
                messages.info(
                    request,
                    "Já existe um envio de certificado em processamento para esta "
                    "empresa.",
                )
        return redirect("company-detail", company_id=company.pk)


class ManualSyncRequestView(CompanyAccessMixin, View):
    def post(self, request: HttpRequest, company_id: int) -> HttpResponse:
        company = self.get_company()
        form = ManualSyncRequestForm(request.POST)
        if not form.is_valid():
            messages.error(request, "Escolha um ambiente fiscal válido.")
            return redirect("company-detail", company_id=company.pk)
        try:
            result = request_synchronization(
                company_id=company.pk,
                environment=form.cleaned_data["environment"],
                trigger=SyncRequest.Trigger.MANUAL,
                actor=request.user,
            )
        except SynchronizationRequestError as error:
            messages.error(request, str(error))
        else:
            if result.created:
                messages.success(
                    request,
                    "Solicitação incluída na fila de sincronização.",
                )
            else:
                messages.info(
                    request,
                    "Já existe uma solicitação ativa para este ambiente.",
                )
        return redirect("company-detail", company_id=company.pk)


class FiscalDocumentListView(LoginRequiredMixin, ListView):
    template_name = "operations/document_list.html"
    context_object_name = "documents"
    paginate_by = 50

    def get_queryset(self) -> QuerySet[FiscalDocument]:
        queryset = FiscalDocument.objects.filter(
            company__in=accessible_companies(self.request.user)
        ).select_related("company")
        term = self.request.GET.get("q", "").strip().upper()
        model = self.request.GET.get("model", "")
        if term:
            queryset = queryset.filter(
                Q(access_key__icontains=term) | Q(company__legal_name__icontains=term)
            )
        if model in {"55", "65"}:
            queryset = queryset.filter(model=model)
        return queryset.order_by("-last_received_at")

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        context["query"] = self.request.GET.get("q", "")
        context["selected_model"] = self.request.GET.get("model", "")
        return context


class FiscalDocumentDownloadView(LoginRequiredMixin, View):
    def get(self, request: HttpRequest, document_id: int) -> FileResponse:
        document = get_object_or_404(
            FiscalDocument.objects.filter(
                company__in=accessible_companies(request.user)
            ),
            pk=document_id,
        )
        try:
            path = FiscalStorage().path_for_read(document.xml_path)
        except FiscalStorageError as error:
            raise Http404("O XML não está disponível no volume configurado.") from error
        AuditLog.objects.create(
            actor=request.user,
            action="fiscal.xml_downloaded",
            target=f"fiscal.document:{document.pk}",
            payload={
                "company_id": document.company_id,
                "xml_sha256": document.xml_sha256,
            },
        )
        return FileResponse(path.open("rb"), as_attachment=True, filename=path.name)
