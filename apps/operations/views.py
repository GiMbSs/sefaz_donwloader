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

from apps.certificates.models import CertificateUpload, DigitalCertificate
from apps.certificates.services.uploads import (
    CertificateUploadError,
    stage_certificate_upload,
)
from apps.fiscal.models import (
    DistributionBatch,
    FiscalDocument,
    NsuControl,
    SyncPolicy,
    SyncRequest,
)
from apps.fiscal.services.distribution import request_distribution_batch_reprocessing
from apps.fiscal.services.storage import FiscalStorage, FiscalStorageError
from apps.fiscal.services.sync import (
    InitialNsuConfigurationError,
    SynchronizationRequestError,
    configure_initial_nsu,
    request_synchronization,
)
from apps.operations.forms import (
    AccountingOfficeForm,
    AlertResolutionForm,
    CertificateUploadForm,
    ClientCompanyCreateForm,
    ClientCompanyForm,
    CompanyArchiveForm,
    InitialNsuForm,
    SyncPolicyForm,
)
from apps.operations.models import AuditLog, OperationAlert
from apps.organizations.access import (
    accessible_companies,
    manageable_companies,
    manageable_offices,
)
from apps.organizations.models import AccountingOffice, ClientCompany, OfficeMembership


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

    def _ensure_installation_administrator(self, request: HttpRequest) -> None:
        if not request.user.is_superuser:
            raise PermissionDenied(
                "Apenas o administrador da instalação pode criar escritórios."
            )

    def get(self, request: HttpRequest) -> HttpResponse:
        self._ensure_installation_administrator(request)
        return render(request, self.template_name, {"form": AccountingOfficeForm()})

    def post(self, request: HttpRequest) -> HttpResponse:
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
        has_nsu_history = (
            company.nsu_controls.filter(
                environment=company.fiscal_environment,
                service="nfe_distribution",
            ).exists()
            or company.sync_requests.filter(
                environment=company.fiscal_environment
            ).exists()
        )
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
                "distribution_batches": company.distribution_batches.order_by(
                    "-created_at"
                )[:12],
                "can_manage": can_manage,
                "can_configure_initial_nsu": can_manage and not has_nsu_history,
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
            {"form": ClientCompanyCreateForm(offices=offices), "is_create": True},
        )

    def post(self, request: HttpRequest) -> HttpResponse:
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
                company = form.save()
                SyncPolicy.objects.create(
                    company=company,
                    mode=SyncPolicy.Mode.HYBRID,
                    frequency=SyncPolicy.Frequency.DAILY,
                    scheduled_time=time(2, 0),
                    is_active=False,
                )
                initial_nsu = form.cleaned_data["initial_nsu"]
                if initial_nsu:
                    configure_initial_nsu(
                        company_id=company.pk,
                        environment=company.fiscal_environment,
                        initial_nsu=initial_nsu,
                        actor=request.user,
                    )
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
                        "environment": company.fiscal_environment,
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
            "Empresa cadastrada. A política automática inicia desativada; "
            "configure-a antes da primeira consulta.",
        )
        return redirect("company-detail", company_id=company.pk)


class CompanyInitialNsuView(CompanyAccessMixin, View):
    """Configure a single continuation cursor before fiscal processing starts."""

    template_name = "operations/initial_nsu_form.html"
    manage_required = True

    @staticmethod
    def _is_configurable(company: ClientCompany) -> bool:
        return not (
            company.nsu_controls.filter(
                environment=company.fiscal_environment,
                service="nfe_distribution",
            ).exists()
            or company.sync_requests.filter(
                environment=company.fiscal_environment
            ).exists()
        )

    def get(self, request: HttpRequest, company_id: int) -> HttpResponse:
        company = self.get_company()
        if not self._is_configurable(company):
            raise PermissionDenied(
                "O NSU inicial só pode ser definido antes da primeira solicitação."
            )
        return render(
            request,
            self.template_name,
            {"company": company, "form": InitialNsuForm(company=company)},
        )

    def post(self, request: HttpRequest, company_id: int) -> HttpResponse:
        company = self.get_company()
        form = InitialNsuForm(request.POST, company=company)
        if not form.is_valid():
            return render(
                request,
                self.template_name,
                {"company": company, "form": form},
                status=400,
            )
        try:
            configure_initial_nsu(
                company_id=company.pk,
                environment=company.fiscal_environment,
                initial_nsu=form.cleaned_data["initial_nsu"],
                actor=request.user,
            )
        except InitialNsuConfigurationError as error:
            form.add_error("initial_nsu", str(error))
            return render(
                request,
                self.template_name,
                {"company": company, "form": form},
                status=400,
            )
        messages.success(
            request,
            "NSU inicial registrado. A próxima consulta continuará após esse valor.",
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
                    "environment": company.fiscal_environment,
                    "status": company.status,
                },
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
            defaults={
                "mode": SyncPolicy.Mode.HYBRID,
                "frequency": SyncPolicy.Frequency.DAILY,
                "scheduled_time": time(2, 0),
                "is_active": False,
            },
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
                    "frequency": policy.frequency,
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


class ManualSyncRequestView(CompanyAccessMixin, View):
    def post(self, request: HttpRequest, company_id: int) -> HttpResponse:
        company = self.get_company()
        try:
            result = request_synchronization(
                company_id=company.pk,
                environment=company.fiscal_environment,
                trigger=SyncRequest.Trigger.MANUAL,
                actor=request.user,
            )
        except SynchronizationRequestError as error:
            messages.error(request, str(error))
        else:
            result.request.refresh_from_db()
            if result.request.status == SyncRequest.Status.FAILED:
                messages.error(request, result.request.result_detail)
            elif result.created:
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


class CompanyArchiveView(CompanyAccessMixin, View):
    """Archive a company after an explicit retention acknowledgement.

    Fiscal records are legal evidence, so this is deliberately not a physical
    database or filesystem delete.  The archived company disappears from normal
    active operations and its policy is disabled.
    """

    template_name = "operations/company_archive_confirm.html"
    manage_required = True

    def get(self, request: HttpRequest, company_id: int) -> HttpResponse:
        company = self.get_company()
        return render(
            request,
            self.template_name,
            {"company": company, "form": CompanyArchiveForm(company=company)},
        )

    def post(self, request: HttpRequest, company_id: int) -> HttpResponse:
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
            SyncPolicy.objects.filter(company=company).update(is_active=False)
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


class DistributionBatchReprocessView(CompanyAccessMixin, View):
    manage_required = True

    def post(
        self, request: HttpRequest, company_id: int, batch_id: int
    ) -> HttpResponse:
        company = self.get_company()
        batch = get_object_or_404(
            DistributionBatch.objects.filter(company=company),
            pk=batch_id,
        )
        submission = request_distribution_batch_reprocessing(batch_id=batch.pk)
        if not submission.created:
            messages.info(
                request,
                "Esse lote não está disponível para um novo reprocessamento local.",
            )
            return redirect("company-detail", company_id=company.pk)
        AuditLog.objects.create(
            actor=request.user,
            action="fiscal.distribution_batch_reprocess_requested",
            target=f"fiscal.distribution_batch:{batch.pk}",
            payload={"company_id": company.pk},
        )

        def dispatch() -> None:
            from apps.fiscal.tasks import reprocess_distribution_batch_task

            reprocess_distribution_batch_task.delay(batch.pk)

        transaction.on_commit(dispatch)
        messages.success(
            request,
            "Reprocessamento local incluído na fila. Nenhuma consulta será enviada "
            "à SEFAZ.",
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
    def post(self, request: HttpRequest, alert_id: int) -> HttpResponse:
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
