from django.urls import reverse


def test_manual_nfce_form_records_model_and_actor(
    client, download_company, download_actor
):
    client.force_login(download_actor)
    response = client.post(
        reverse("company-download-create", args=[download_company.pk]),
        {
            "start_date": "2024-10-10",
            "end_date": "2024-10-10",
            "formats": ["xml", "txt"],
            "document_model": "65",
        },
    )
    assert response.status_code == 302
    request = download_company.download_requests.get()
    assert request.document_model == "65"
    assert request.requested_by == download_actor
    response = client.get(reverse("company-download-list", args=[download_company.pk]))
    assert b"NFC-e" in response.content


def test_automatic_policy_form_exposes_both_models(download_company):
    from apps.operations.download_forms import DownloadPolicyForm

    form = DownloadPolicyForm()
    assert dict(form.fields["document_models"].choices) == {"55": "NF-e", "65": "NFC-e"}


def test_document_list_can_filter_nfce(client, download_company, download_actor):
    from datetime import date

    from apps.fiscal.models import InvoiceDocument

    first = InvoiceDocument.objects.create(
        company=download_company,
        access_key="1" * 44,
        model="55",
        number=1,
        issued_on=date(2024, 10, 10),
    )
    second = InvoiceDocument.objects.create(
        company=download_company,
        access_key="2" * 44,
        model="65",
        number=2,
        issued_on=date(2024, 10, 10),
    )
    client.force_login(download_actor)
    response = client.get(reverse("document-list"), {"document_model": "65"})
    assert [item.pk for item in response.context["documents"]] == [second.pk]
    assert first.access_key.encode() not in response.content
    assert b"NFC-e" in response.content
