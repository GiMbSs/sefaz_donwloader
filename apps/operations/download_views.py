from typing import Any

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.http import FileResponse, Http404, HttpResponseGone
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View
from django.views.generic import TemplateView

from apps.fiscal.atf.errors import AtfError
from apps.fiscal.atf.types import Period
from apps.fiscal.models import (
    ArchiveMember,
    DownloadArchive,
    DownloadPart,
    DownloadRequest,
    FiscalEvent,
    InvoiceDocument,
)
from apps.fiscal.services.download_recovery import (
    abandon_uncertain_submission,
    recover_download_request,
)
from apps.fiscal.services.downloads import request_download
from apps.fiscal.services.leases import bind_remote_result
from apps.fiscal.services.periods import active_request_key
from apps.fiscal.services.storage import FiscalStorage, FiscalStorageError
from apps.operations.models import AuditLog
from apps.organizations.access import accessible_companies, manageable_companies

from .download_forms import DownloadRequestForm, RemoteResultResolutionForm
from .http import (
    AuthenticatedViewMixin as LoginRequiredMixin,
)
from .http import (
    TypedListView as ListView,
)
from .views import CompanyAccessMixin


def _download(path: Any, filename: Any, content_type: Any) -> Any:
    try:
        stream = FiscalStorage().path_for_read(path).open("rb")
    except (FiscalStorageError, OSError):
        raise Http404("Arquivo indisponível no armazenamento local.") from None
    response = FileResponse(
        stream, as_attachment=True, filename=filename, content_type=content_type
    )
    response["Cache-Control"] = "private, no-store"
    response["X-Content-Type-Options"] = "nosniff"
    return response


class DownloadRequestCreateView(CompanyAccessMixin, View):
    template_name = "operations/download_request_form.html"

    def get(self, request: Any, company_id: Any) -> Any:
        company = self.get_company()
        return render(
            request,
            self.template_name,
            {"company": company, "form": DownloadRequestForm()},
        )

    def post(self, request: Any, company_id: Any) -> Any:
        company = self.get_company()
        form = DownloadRequestForm(request.POST)
        if form.is_valid():
            period = Period(
                form.cleaned_data["start_date"], form.cleaned_data["end_date"]
            )
            formats = tuple(form.cleaned_data["formats"])
            previous = None
            if form.cleaned_data["repeat"]:
                previous = (
                    DownloadRequest.objects.filter(
                        company=company,
                        active_key=active_request_key(
                            company.pk,
                            period,
                            formats,
                            form.cleaned_data["document_model"],
                        ),
                    )
                    .order_by("-created_at")
                    .first()
                )
            try:
                if company.status != "active":
                    raise ValidationError(
                        "Ative a empresa antes de solicitar novos arquivos."
                    )
                result = request_download(
                    company_id=company.pk,
                    period=period,
                    formats=formats,
                    document_model=form.cleaned_data["document_model"],
                    actor_id=request.user.pk,
                    trigger="manual",
                    repeat_of=previous.pk if previous else None,
                )
            except ValidationError as error:
                form.add_error(None, error)
            else:
                messages.success(
                    request,
                    "Pedido registrado. Acompanhe o processamento "
                    "e os arquivos disponíveis.",
                )
                return redirect("download-request-detail", request_id=result.pk)
        return render(
            request, self.template_name, {"company": company, "form": form}, status=400
        )


class DownloadAccessMixin(LoginRequiredMixin):
    def get_download(self) -> Any:
        return get_object_or_404(
            DownloadRequest.objects.select_related("company"),
            pk=self.kwargs["request_id"],
            company__in=accessible_companies(self.request.user),
        )


class DownloadRequestDetailView(DownloadAccessMixin, TemplateView):
    template_name = "operations/download_request_detail.html"

    def get_context_data(self, **kwargs: Any) -> Any:
        context = super().get_context_data(**kwargs)
        download = self.get_download()
        context.update(
            download=download,
            parts=download.parts.prefetch_related("archives__members", "attempts"),
            can_manage=download.company.status == "active"
            and manageable_companies(self.request.user)
            .filter(pk=download.company_id)
            .exists(),
            can_recover=download.company.status == "active"
            and download.status not in {"succeeded", "empty", "cancelled"},
        )
        return context


class DownloadRequestListView(LoginRequiredMixin, ListView):
    template_name = "operations/download_request_list.html"
    context_object_name = "downloads"
    paginate_by = 25

    def get_queryset(self) -> Any:
        queryset = (
            DownloadRequest.objects.filter(
                company__in=accessible_companies(self.request.user)
            )
            .select_related("company", "requested_by")
            .prefetch_related("parts")
        )
        self.company = None
        if "company_id" in self.kwargs:
            self.company = get_object_or_404(
                accessible_companies(self.request.user), pk=self.kwargs["company_id"]
            )
            queryset = queryset.filter(company=self.company)
        term = self.request.GET.get("q", "").strip()
        if term:
            queryset = queryset.filter(
                Q(company__legal_name__icontains=term)
                | Q(company__tax_identifier__icontains=term)
            )
        return queryset.order_by("-created_at")

    def get_context_data(self, **kwargs: Any) -> Any:
        context = super().get_context_data(**kwargs)
        context["query"] = self.request.GET.get("q", "")
        context["company"] = self.company
        return context


class DownloadRequestRecoverView(DownloadAccessMixin, View):
    def post(self, request: Any, request_id: Any) -> Any:
        download = self.get_download()
        try:
            if download.company.status != "active":
                raise ValidationError("Ative a empresa antes de retomar o pedido.")
            result = recover_download_request(
                download.pk,
                actor_id=request.user.pk,
                note=request.POST.get("note", "Retomada pela interface"),
            )
        except ValidationError as error:
            messages.error(request, "; ".join(error.messages))
        else:
            messages.info(
                request,
                "Há resultados que exigem revisão do administrador."
                if result.requires_review
                else "Retomada registrada; os pedidos incertos serão conciliados "
                "antes de qualquer novo envio.",
            )
        return redirect("download-request-detail", request_id=download.pk)


class DownloadArchiveView(LoginRequiredMixin, View):
    def get(self, request: Any, archive_id: Any) -> Any:
        archive = get_object_or_404(
            DownloadArchive.objects.select_related("part__request"),
            pk=archive_id,
            part__request__company__in=accessible_companies(request.user),
            validation_status="valid",
        )
        AuditLog.objects.create(
            actor=request.user,
            action="fiscal.zip_downloaded",
            target=f"archive:{archive.pk}",
        )
        return _download(archive.path, archive.filename, "application/zip")


class DownloadArchiveRevalidateView(LoginRequiredMixin, View):
    def post(self, request: Any, archive_id: Any) -> Any:
        archive = get_object_or_404(
            DownloadArchive.objects.select_related("part__request"),
            pk=archive_id,
            part__request__company__in=manageable_companies(request.user),
        )
        from apps.fiscal.tasks import revalidate_download_archive

        revalidate_download_archive.delay(str(archive.pk))
        AuditLog.objects.create(
            actor=request.user,
            action="fiscal.archive_revalidation_requested",
            target=f"archive:{archive.pk}",
        )
        messages.success(
            request, "Revalidação local solicitada. Esta ação não consulta o ATF."
        )
        return redirect("download-request-detail", request_id=archive.part.request_id)


class RemoteResultResolutionView(LoginRequiredMixin, View):
    template_name = "operations/remote_result_resolution.html"

    def get_part(self) -> Any:
        return get_object_or_404(
            DownloadPart.objects.select_related("request__company"),
            pk=self.kwargs["part_id"],
            request__company__in=manageable_companies(self.request.user),
            request__company__status="active",
        )

    def get(self, request: Any, part_id: Any) -> Any:
        part = self.get_part()
        return render(
            request,
            self.template_name,
            {
                "part": part,
                "form": RemoteResultResolutionForm(candidates=part.candidates),
            },
        )

    def post(self, request: Any, part_id: Any) -> Any:
        part = self.get_part()
        form = RemoteResultResolutionForm(request.POST, candidates=part.candidates)
        if form.is_valid():
            try:
                if form.cleaned_data["abandon"]:
                    abandon_uncertain_submission(
                        part.pk,
                        actor_id=request.user.pk,
                        note=form.cleaned_data["note"],
                        acknowledge_remote_uncertainty=form.cleaned_data["acknowledge"],
                    )
                else:
                    bind_remote_result(
                        part.pk,
                        part.remote_account_key,
                        form.cleaned_data["candidate"],
                        actor_id=request.user.pk,
                    )
                    recover_download_request(
                        part.request_id,
                        actor_id=request.user.pk,
                        note=form.cleaned_data["note"],
                    )
            except (ValidationError, AtfError):
                form.add_error(
                    None,
                    "Não foi possível confirmar esta ação. O resultado pode estar "
                    "em uso ou ainda não estar comprovado.",
                )
            else:
                messages.success(
                    request,
                    "Decisão registrada. Nenhum novo pedido foi enviado por esta ação.",
                )
                return redirect("download-request-detail", request_id=part.request_id)
        return render(
            request, self.template_name, {"part": part, "form": form}, status=400
        )


class InvoiceDocumentListView(LoginRequiredMixin, ListView):
    template_name = "operations/document_list.html"
    context_object_name = "documents"
    paginate_by = 25

    def get_queryset(self) -> Any:
        companies = accessible_companies(self.request.user)
        self.kind = self.request.GET.get("kind", "invoice")
        self.document_model = self.request.GET.get("document_model", "")
        if self.document_model not in {"55", "65"}:
            self.document_model = ""
        term = self.request.GET.get("q", "").strip()
        if self.kind == "event":
            queryset: Any = FiscalEvent.objects.filter(
                company__in=companies
            ).select_related("company")
        elif self.kind == "txt":
            queryset = ArchiveMember.objects.filter(
                kind="txt", archive__part__request__company__in=companies
            ).select_related("archive__part__request__company")
            if term:
                queryset = queryset.filter(
                    Q(archive__part__request__company__legal_name__icontains=term)
                    | Q(archive__part__request__company__tax_identifier__icontains=term)
                )
            if self.document_model:
                queryset = queryset.filter(
                    archive__part__request__document_model=self.document_model
                )
            return queryset.order_by("-pk")
        else:
            self.kind = "invoice"
            queryset = (
                InvoiceDocument.objects.filter(company__in=companies)
                .select_related("company")
                .prefetch_related("versions")
            )
        if term:
            queryset = queryset.filter(
                Q(access_key__icontains=term)
                | Q(company__legal_name__icontains=term)
                | Q(company__tax_identifier__icontains=term)
            )
            if self.kind == "invoice" and term.isdecimal():
                queryset = (
                    InvoiceDocument.objects.filter(company__in=companies)
                    .filter(Q(pk__in=queryset.values("pk")) | Q(number=int(term)))
                    .select_related("company")
                    .prefetch_related("versions")
                )
        if self.document_model:
            if self.kind == "invoice":
                queryset = queryset.filter(model=self.document_model)
            else:
                queryset = queryset.filter(
                    access_key__regex=r"^.{20}" + self.document_model
                )
        return queryset.order_by("-pk")

    def get_context_data(self, **kwargs: Any) -> Any:
        context = super().get_context_data(**kwargs)
        context.update(
            kind=self.kind,
            query=self.request.GET.get("q", ""),
            document_model=self.document_model,
        )
        return context


class InvoiceXmlDownloadView(LoginRequiredMixin, View):
    def get(self, request: Any, document_id: Any) -> Any:
        document = get_object_or_404(
            InvoiceDocument,
            pk=document_id,
            company__in=accessible_companies(request.user),
        )
        version = document.versions.order_by("-created_at").first()
        if version is None:
            raise Http404()
        return _download(version.path, f"{document.access_key}.xml", "application/xml")


class EventXmlDownloadView(LoginRequiredMixin, View):
    def get(self, request: Any, event_id: Any) -> Any:
        event = get_object_or_404(
            FiscalEvent, pk=event_id, company__in=accessible_companies(request.user)
        )
        return _download(
            event.path,
            f"{event.access_key}-{event.event_type}-{event.sequence}.xml",
            "application/xml",
        )


class ArchiveMemberDownloadView(LoginRequiredMixin, View):
    def get(self, request: Any, member_id: Any) -> Any:
        member = get_object_or_404(
            ArchiveMember,
            pk=member_id,
            archive__part__request__company__in=accessible_companies(request.user),
            kind="txt",
        )
        return _download(member.path, "relatorio-nfe.txt", "text/plain")


@login_required
def retired_fiscal_endpoint(request: Any, **kwargs: Any) -> Any:
    return HttpResponseGone(
        "Esta operação foi substituída pelos downloads por período da SEFAZ-PB."
    )
