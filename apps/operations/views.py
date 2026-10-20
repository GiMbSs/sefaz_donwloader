"""Authenticated views for the accounting workstation."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Q, QuerySet
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views import View
from django.views.generic import TemplateView

from apps.certificates.models import CertificateUpload, DigitalCertificate
from apps.certificates.services.uploads import (
    CertificateUploadError,
    stage_certificate_upload,
)
from apps.fiscal.models import (
    DownloadPolicy,
    DownloadRequest,
)
from apps.operations.download_forms import DownloadPolicyForm
from apps.operations.forms import (
    AccountingOfficeForm,
    AlertResolutionForm,
    CertificateUploadForm,
    ClientCompanyCreateForm,
    ClientCompanyForm,
    CompanyArchiveForm,
)
from apps.operations.models import AuditLog, OperationAlert
from apps.organizations.access import (
    accessible_companies,
    manageable_companies,
    manageable_offices,
)
from apps.organizations.models import AccountingOffice, ClientCompany, OfficeMembership

from .http import (
    AuthenticatedHttpRequest,
)
from .http import (
    AuthenticatedViewMixin as LoginRequiredMixin,
)
from .http import (
    TypedListView as ListView,
)


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
                "can_create_company": manageable_offices(self.request.user).exists(),
                "can_create_office": self.request.user.is_superuser,
                "has_offices": AccountingOffice.objects.exists(),
                "company_count": companies.count(),
                "active_company_count": active_company_ids.count(),
                "waiting_request_count": DownloadRequest.objects.filter(
                    company_id__in=active_company_ids,
                    status="waiting",
                ).count(),
                "expiring_certificates": DigitalCertificate.objects.filter(
                    company_id__in=active_company_ids,
                    status=DigitalCertificate.Status.ACTIVE,
                    not_valid_after__lte=expiry_limit,
                ).select_related("company"),
                "recent_requests": DownloadRequest.objects.filter(
                    company_id__in=active_company_ids
                )
                .select_related("company", "requested_by")
                .order_by("-created_at")[:8],
                "open_alerts": OperationAlert.objects.filter(
                    company_id__in=active_company_ids,
                    status=OperationAlert.Status.OPEN,
                )
                .select_related("company")
                .order_by("-created_at")[:8],
                "open_alert_count": OperationAlert.objects.filter(
                    company_id__in=active_company_ids,
                    status=OperationAlert.Status.OPEN,
                ).count(),
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
        else:
            queryset = queryset.exclude(status=ClientCompany.Status.ARCHIVED)
        return queryset.order_by("legal_name")

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        context["can_create_company"] = manageable_offices(self.request.user).exists()
        context["can_create_office"] = self.request.user.is_superuser
        context["has_offices"] = AccountingOffice.objects.exists()
        context["selected_status"] = self.request.GET.get("status", "")
        context["query"] = self.request.GET.get("q", "")
        context["status_choices"] = ClientCompany.Status.choices
        return context


class OfficeCreateView(LoginRequiredMixin, View):
    """Create an accounting-office tenant during controlled initial setup."""

    template_name = "operations/office_form.html"

    def _ensure_installation_administrator(
        self, request: AuthenticatedHttpRequest
    ) -> None:
        if not request.user.is_superuser:
            raise PermissionDenied(
                "Apenas o administrador da instalação pode criar escritórios."
            )

    def get(self, request: AuthenticatedHttpRequest) -> HttpResponse:
        self._ensure_installation_administrator(request)
        return render(request, self.template_name, {"form": AccountingOfficeForm()})

    def post(self, request: AuthenticatedHttpRequest) -> HttpResponse:
        self._ensure_installation_administrator(request)
        form = AccountingOfficeForm(request.POST)
        if not form.is_valid():
            return render(request, self.template_name, {"form": form}, status=400)
        with transaction.atomic():
            office = form.save()
            OfficeMembership.objects.create(
                office=office,
                user=request.user,
                role=OfficeMembership.Role.ADMIN,
                is_active=True,
            )
            AuditLog.objects.create(
                actor=request.user,
                action="organizations.office_created",
                target=f"organizations.accounting_office:{office.pk}",
                payload={"tax_identifier": office.tax_identifier},
            )
        messages.success(
            request,
            "Escritório cadastrado. Agora cadastre a primeira empresa cliente.",
        )
        return redirect("company-create")


class CompanyAccessMixin(LoginRequiredMixin):
    manage_required = False

    def get_company(self) -> ClientCompany:
        queryset = (
            manageable_companies(self.request.user)
            if self.manage_required
            else accessible_companies(self.request.user)
        )
        company = get_object_or_404(
            queryset.select_related("office"),
            pk=self.kwargs["company_id"],
        )
        if self.manage_required and company.status == ClientCompany.Status.ARCHIVED:
            raise PermissionDenied("A empresa está arquivada para a operação diária.")
        return company


class CompanyDetailView(CompanyAccessMixin, TemplateView):
    template_name = "operations/company_detail.html"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        company = self.get_company()
        can_manage = company.status != ClientCompany.Status.ARCHIVED and (
            manageable_companies(self.request.user).filter(pk=company.pk).exists()
        )
        context.update(
            {
                "company": company,
                "policy": getattr(company, "download_policy", None),
                "active_certificate": company.digital_certificates.filter(
                    status=DigitalCertificate.Status.ACTIVE
                ).first(),
                "latest_certificate_upload": company.certificate_uploads.order_by(
                    "-created_at"
                ).first(),
                "download_requests": company.download_requests.select_related(
                    "requested_by"
                ).order_by("-created_at")[:12],
                "documents": company.invoices.order_by("-last_received_at")[:12],
                "can_manage": can_manage,
            }
        )
        return context


class CompanyCreateView(LoginRequiredMixin, View):
    template_name = "operations/company_form.html"

    def _offices(self) -> Any:
        return manageable_offices(self.request.user)

    def get(self, request: AuthenticatedHttpRequest) -> HttpResponse:
        offices = self._offices()
        if not offices.exists():
            raise PermissionDenied("Seu perfil não administra nenhum escritório.")
        return render(
            request,
            self.template_name,
            {"form": ClientCompanyCreateForm(offices=offices), "is_create": True},
        )

    def post(self, request: AuthenticatedHttpRequest) -> HttpResponse:
        offices = self._offices()
        if not offices.exists():
            raise PermissionDenied("Seu perfil não administra nenhum escritório.")
        form = ClientCompanyCreateForm(request.POST, request.FILES, offices=offices)
        if not form.is_valid():
            return render(
                request,
                self.template_name,
                {"form": form, "is_create": True},
                status=400,
            )
        try:
            with transaction.atomic():
                company = form.save(commit=False)
                company.save()
                DownloadPolicy.objects.create(company=company)
                certificate_file = form.cleaned_data.get("certificate_file")
                if certificate_file is not None:
                    stage_certificate_upload(
                        company_id=company.pk,
                        filename=certificate_file.name,
                        payload=certificate_file.read(),
                        password=form.cleaned_data["certificate_password"],
                        uploaded_by=request.user,
                    )
                AuditLog.objects.create(
                    actor=request.user,
                    action="organizations.company_created",
                    target=f"organizations.client_company:{company.pk}",
                    payload={
                        "office_id": company.office_id,
                        "certificate_staged": certificate_file is not None,
                    },
                )
        except CertificateUploadError as error:
            form.add_error("certificate_file", str(error))
            return render(
                request,
                self.template_name,
                {"form": form, "is_create": True},
                status=400,
            )
        messages.success(
            request,
            "Empresa cadastrada. Solicite arquivos por período "
            "ou configure o agendamento automático.",
        )
        return redirect("company-detail", company_id=company.pk)


class CompanyUpdateView(CompanyAccessMixin, View):
    template_name = "operations/company_form.html"
    manage_required = True

    def get(self, request: AuthenticatedHttpRequest, company_id: int) -> HttpResponse:
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

    def post(self, request: AuthenticatedHttpRequest, company_id: int) -> HttpResponse:
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
        changed_fields = sorted(form.changed_data)
        with transaction.atomic():
            company = form.save()
            AuditLog.objects.create(
                actor=request.user,
                action="organizations.company_updated",
                target=f"organizations.client_company:{company.pk}",
                payload={
                    "office_id": company.office_id,
                    "changed_fields": changed_fields,
                    "status": company.status,
                },
            )
        messages.success(request, "Cadastro da empresa atualizado.")
        return redirect("company-detail", company_id=company.pk)


class CompanyPolicyUpdateView(CompanyAccessMixin, View):
    template_name = "operations/policy_form.html"
    manage_required = True

    def get_policy(self) -> DownloadPolicy:
        company = self.get_company()
        policy, _ = DownloadPolicy.objects.get_or_create(company=company)
        return policy

    def get(self, request: AuthenticatedHttpRequest, company_id: int) -> HttpResponse:
        policy = self.get_policy()
        return render(
            request,
            self.template_name,
            {"form": DownloadPolicyForm(instance=policy), "company": policy.company},
        )

    def post(self, request: AuthenticatedHttpRequest, company_id: int) -> HttpResponse:
        policy = self.get_policy()
        form = DownloadPolicyForm(request.POST, instance=policy)
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
                action="fiscal.download_policy_updated",
                target=f"fiscal.download_policy:{policy.pk}",
                payload={
                    "company_id": policy.company_id,
                    "mode": policy.mode,
                    "frequency": policy.frequency,
                    "is_active": policy.is_active,
                    "period_strategy": policy.period_strategy,
                    "formats": policy.formats,
                },
            )
        messages.success(request, "Agendamento de downloads atualizado.")
        return redirect("company-detail", company_id=policy.company_id)


class CompanyCertificateUploadView(CompanyAccessMixin, View):
    template_name = "operations/certificate_upload.html"
    manage_required = True

    def get(self, request: AuthenticatedHttpRequest, company_id: int) -> HttpResponse:
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

    def post(self, request: AuthenticatedHttpRequest, company_id: int) -> HttpResponse:
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
                    "Certificado recebido. Aguarde a validação para utilizá-lo.",
                )
            else:
                if result.upload.status == CertificateUpload.Status.SUBMITTED:
                    messages.info(
                        request,
                        "Já havia um envio de certificado pendente; ele foi "
                        "recolocado na fila de processamento.",
                    )
                else:
                    messages.info(
                        request,
                        "Já existe um envio de certificado em processamento para "
                        "esta empresa.",
                    )
        return redirect("company-detail", company_id=company.pk)


class CompanyArchiveView(CompanyAccessMixin, View):
    """Archive a company after an explicit retention acknowledgement.

    Fiscal records are legal evidence, so this is deliberately not a physical
    database or filesystem delete.  The archived company disappears from normal
    active operations and its policy is disabled.
    """

    template_name = "operations/company_archive_confirm.html"
    manage_required = True

    def get(self, request: AuthenticatedHttpRequest, company_id: int) -> HttpResponse:
        company = self.get_company()
        return render(
            request,
            self.template_name,
            {"company": company, "form": CompanyArchiveForm(company=company)},
        )

    def post(self, request: AuthenticatedHttpRequest, company_id: int) -> HttpResponse:
        company = self.get_company()
        form = CompanyArchiveForm(request.POST, company=company)
        if not form.is_valid():
            return render(
                request,
                self.template_name,
                {"company": company, "form": form},
                status=400,
            )
        with transaction.atomic():
            company.status = ClientCompany.Status.ARCHIVED
            company.save(update_fields=("status", "updated_at"))
            DownloadPolicy.objects.filter(company=company).update(is_active=False)
            AuditLog.objects.create(
                actor=request.user,
                action="organizations.company_archived",
                target=f"organizations.client_company:{company.pk}",
                payload={
                    "office_id": company.office_id,
                    "tax_identifier": company.tax_identifier,
                    "reason": "explicit_retention_acknowledgement",
                },
            )
        messages.warning(
            request,
            "Empresa arquivada. Os arquivos e evidências fiscais foram preservados; "
            "a política automática foi desativada.",
        )
        return redirect("company-list")


class OperationAlertListView(LoginRequiredMixin, ListView):
    template_name = "operations/alert_list.html"
    context_object_name = "alerts"
    paginate_by = 50

    def get_queryset(self) -> QuerySet[OperationAlert]:
        queryset = OperationAlert.objects.filter(
            company__in=accessible_companies(self.request.user)
        ).select_related("company", "resolved_by")
        status = self.request.GET.get("status", "open")
        severity = self.request.GET.get("severity", "")
        if status not in OperationAlert.Status.values:
            status = OperationAlert.Status.OPEN
        queryset = queryset.filter(status=status)
        if severity in OperationAlert.Severity.values:
            queryset = queryset.filter(severity=severity)
        return queryset

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        selected_status = self.request.GET.get("status", OperationAlert.Status.OPEN)
        if selected_status not in OperationAlert.Status.values:
            selected_status = OperationAlert.Status.OPEN
        context.update(
            {
                "selected_status": selected_status,
                "selected_severity": self.request.GET.get("severity", ""),
                "status_choices": OperationAlert.Status.choices,
                "severity_choices": OperationAlert.Severity.choices,
                "manageable_company_ids": set(
                    manageable_companies(self.request.user).values_list("pk", flat=True)
                ),
            }
        )
        return context


class OperationAlertResolveView(LoginRequiredMixin, View):
    def post(self, request: AuthenticatedHttpRequest, alert_id: int) -> HttpResponse:
        alert = get_object_or_404(
            OperationAlert.objects.filter(
                company__in=manageable_companies(request.user)
            ),
            pk=alert_id,
        )
        form = AlertResolutionForm(request.POST)
        if not form.is_valid():
            messages.error(request, "Não foi possível registrar a resolução do alerta.")
            return redirect("alert-list")
        with transaction.atomic():
            alert = OperationAlert.objects.select_for_update().get(pk=alert.pk)
            if alert.status == OperationAlert.Status.RESOLVED:
                messages.info(request, "Este alerta já estava resolvido.")
                return redirect("alert-list")
            alert.status = OperationAlert.Status.RESOLVED
            alert.resolved_by = request.user
            alert.resolved_at = timezone.now()
            alert.resolution_note = form.cleaned_data["resolution_note"]
            alert.save(
                update_fields=(
                    "status",
                    "resolved_by",
                    "resolved_at",
                    "resolution_note",
                    "updated_at",
                )
            )
            AuditLog.objects.create(
                actor=request.user,
                action="operations.alert_resolved",
                target=f"operations.alert:{alert.pk}",
                payload={"company_id": alert.company_id, "code": alert.code},
            )
        messages.success(request, "Alerta marcado como resolvido.")
        return redirect("alert-list")
