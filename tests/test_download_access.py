from datetime import date

import pytest
from django.urls import reverse

from apps.fiscal.atf.types import Period


@pytest.fixture
def owned_archive(download_company, download_actor, tmp_path, settings):
    from apps.fiscal.models import DownloadArchive
    from apps.fiscal.services.downloads import request_download

    settings.FISCAL_NOTES_ROOT = tmp_path
    (tmp_path / "owned.zip").write_bytes(b"owned private bytes")
    request = request_download(
        company_id=download_company.pk,
        period=Period(date(2024, 1, 1), date(2024, 1, 2)),
        formats=("xml",),
        actor_id=download_actor.pk,
        trigger="manual",
        dispatch=False,
    )
    archive = DownloadArchive.objects.create(
        part=request.parts.get(),
        remote_account_key="a" * 64,
        message_id="10",
        attachment_index=0,
        filename="notes.zip",
        path="owned.zip",
        sha256="b" * 64,
        byte_count=19,
    )
    return archive


@pytest.mark.django_db(transaction=True)
def test_zip_download_is_scoped_to_office(client, owned_archive, download_actor):
    from django.contrib.auth import get_user_model

    client.force_login(download_actor)
    response = client.get(reverse("download-archive", args=[owned_archive.pk]))
    assert response.status_code == 200
    assert b"".join(response.streaming_content) == b"owned private bytes"
    response.close()
    outsider = get_user_model().objects.create_user(email="outsider@example.test")
    client.force_login(outsider)
    assert (
        client.get(reverse("download-archive", args=[owned_archive.pk])).status_code
        == 404
    )
    assert (
        client.get(
            reverse("download-request-detail", args=[owned_archive.part.request_id])
        ).status_code
        == 404
    )


def test_request_recovery_does_not_accept_another_office(client, owned_archive):
    from django.contrib.auth import get_user_model

    outsider = get_user_model().objects.create_user(email="outsider@example.test")
    client.force_login(outsider)
    response = client.post(
        reverse("download-request-recover", args=[owned_archive.part.request_id])
    )
    assert response.status_code == 404


def test_technical_admin_does_not_cross_offices(owned_archive, download_actor, rf):
    from django.contrib import admin

    from apps.fiscal.models import DownloadRequest
    from apps.organizations.models import (
        AccountingOffice,
        ClientCompany,
        OfficeMembership,
    )

    OfficeMembership.objects.filter(user=download_actor).update(role="admin")
    download_actor.is_staff = True
    download_actor.save()
    office = AccountingOffice.objects.create(
        legal_name="Other", tax_identifier="11222333000181"
    )
    company = ClientCompany.objects.create(
        office=office, legal_name="Other company", tax_identifier="11222333000181"
    )
    other = DownloadRequest.objects.create(
        company=company,
        start_date=date(2024, 1, 1),
        end_date=date(2024, 1, 2),
        active_key="other",
    )
    request = rf.get("/admin/fiscal/downloadrequest/")
    request.user = download_actor
    model_admin = admin.site._registry[DownloadRequest]
    ids = set(model_admin.get_queryset(request).values_list("pk", flat=True))
    assert owned_archive.part.request_id in ids
    assert other.pk not in ids
