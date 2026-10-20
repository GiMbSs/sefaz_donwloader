from datetime import date

from django.urls import reverse


def test_download_form_requests_explicit_period_and_both_formats(
    client, download_company, download_actor
):
    client.force_login(download_actor)
    response = client.get(
        reverse("company-download-create", args=[download_company.pk])
    )
    assert response.status_code == 200
    assert {"start_date", "end_date", "formats"} <= set(response.context["form"].fields)
    assert response.context["form"].fields["formats"].initial == ["xml", "txt"]
    response = client.post(
        reverse("company-download-create", args=[download_company.pk]),
        {
            "start_date": "2024-10-01",
            "document_model": "55",
            "end_date": "2024-10-18",
            "formats": ["xml", "txt"],
        },
    )
    assert response.status_code == 302
    request = download_company.download_requests.get()
    assert request.parts.count() == 2


def test_company_detail_replaces_cursor_action_with_period_download(
    client, download_company, download_actor
):
    client.force_login(download_actor)
    response = client.get(reverse("company-detail", args=[download_company.pk]))
    assert response.status_code == 200
    assert (
        reverse("company-download-create", args=[download_company.pk]).encode()
        in response.content
    )
    assert b"Corrigir cursor NSU" not in response.content


def test_company_form_does_not_offer_obsolete_nsu_or_environment(download_company):
    from apps.operations.forms import ClientCompanyCreateForm

    form = ClientCompanyCreateForm()
    assert "initial_nsu" not in form.fields
    assert "fiscal_environment" not in form.fields


def test_nsu_endpoint_is_gone_and_does_not_create_request(
    client, download_company, download_actor
):
    client.force_login(download_actor)
    response = client.post(f"/empresas/{download_company.pk}/nsu/", {"last_nsu": "123"})
    assert response.status_code == 410
    assert not download_company.download_requests.exists()


def test_company_download_history_lists_manual_actor_and_automatic_origin(
    client, download_company, download_actor
):
    from apps.fiscal.models import DownloadRequest

    manual = DownloadRequest.objects.create(
        company=download_company,
        start_date=date(2024, 10, 1),
        end_date=date(2024, 10, 2),
        active_key="manual-history",
        trigger="manual",
        requested_by=download_actor,
    )
    automatic = DownloadRequest.objects.create(
        company=download_company,
        start_date=date(2024, 10, 3),
        end_date=date(2024, 10, 4),
        active_key="auto-history",
        trigger="scheduled",
    )
    client.force_login(download_actor)
    response = client.get(reverse("company-download-list", args=[download_company.pk]))
    assert response.status_code == 200
    assert {item.pk for item in response.context["downloads"]} == {
        manual.pk,
        automatic.pk,
    }
    assert download_actor.email.encode() in response.content
    assert "Automático".encode() in response.content
    response = client.get(
        reverse("company-download-list", args=[download_company.pk + 9999])
    )
    assert response.status_code == 404


def test_manual_request_requires_both_dates(client, download_company, download_actor):
    client.force_login(download_actor)
    response = client.post(
        reverse("company-download-create", args=[download_company.pk]),
        {
            "start_date": "2024-10-01",
            "document_model": "55",
            "formats": ["xml"],
        },
    )
    assert response.status_code == 400
    assert "end_date" in response.context["form"].errors
    assert not download_company.download_requests.exists()


def test_document_search_accepts_long_numeric_input(
    client, download_company, download_actor
):
    client.force_login(download_actor)

    response = client.get(reverse("document-list"), {"q": "1" * 5000})

    assert response.status_code == 200
    assert not response.context["documents"]


def test_document_search_preserves_number_and_full_access_key_lookups(
    client, download_company, download_actor
):
    from apps.fiscal.models import InvoiceDocument

    document = InvoiceDocument.objects.create(
        company=download_company,
        access_key="2" * 44,
        model="55",
        number=123456789,
        issued_on=date(2024, 10, 10),
    )
    client.force_login(download_actor)

    for term in (str(document.number), document.access_key):
        response = client.get(reverse("document-list"), {"q": term})

        assert response.status_code == 200
        assert list(response.context["documents"]) == [document]
