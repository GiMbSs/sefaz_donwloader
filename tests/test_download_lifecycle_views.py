import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from apps.fiscal.models import DownloadRequest
from apps.fiscal.services.download_lifecycle import cancel_download_request
from apps.organizations.models import OfficeMembership


@pytest.mark.parametrize("action", ["cancel", "delete"])
def test_action_is_admin_only_and_cannot_cross_offices(
    client, lifecycle_request, lifecycle_admin, action
):
    url = reverse(f"download-request-{action}", args=[lifecycle_request.pk])
    OfficeMembership.objects.filter(user=lifecycle_admin).update(role="operator")
    client.force_login(lifecycle_admin)
    assert client.get(url).status_code == 404
    assert client.post(url, {"note": "Teste", "confirm": "on"}).status_code == 404
    lifecycle_admin.is_staff = True
    lifecycle_admin.save()
    assert client.post(url, {"note": "Teste", "confirm": "on"}).status_code == 404
    outsider = get_user_model().objects.create_user(
        email="outside-lifecycle@test.local"
    )
    client.force_login(outsider)
    assert client.post(url, {"note": "Teste", "confirm": "on"}).status_code == 404


def test_cancel_then_delete_requires_confirmation_and_removes_operational_links(
    client, lifecycle_request, lifecycle_admin
):
    request = lifecycle_request
    client.force_login(lifecycle_admin)
    detail = reverse("download-request-detail", args=[request.pk])
    cancel = reverse("download-request-cancel", args=[request.pk])
    delete = reverse("download-request-delete", args=[request.pk])
    assert cancel in client.get(detail).content.decode()
    assert client.get(cancel).status_code == 200
    request.refresh_from_db()
    assert request.status == "queued"
    assert client.post(cancel, {"note": "Teste"}).status_code == 400
    assert client.post(cancel, {"confirm": "on"}).status_code == 400
    assert client.post(delete, {"note": "Teste", "confirm": "on"}).status_code == 400
    assert (
        client.post(cancel, {"note": "Cancelar teste", "confirm": "on"}).status_code
        == 302
    )
    request.refresh_from_db()
    assert request.status == "cancelled"
    html = client.get(detail).content.decode()
    assert delete in html
    assert "Retomar pedido" not in html
    assert client.get(delete).status_code == 200
    assert (
        client.post(delete, {"note": "Excluir teste", "confirm": "on"}).status_code
        == 302
    )
    request.refresh_from_db()
    assert request.deleted_at is not None
    assert client.get(detail).status_code == 404
    assert (
        client.post(reverse("download-request-recover", args=[request.pk])).status_code
        == 404
    )
    assert client.get(cancel).status_code == 404
    assert client.get(delete).status_code == 404
    for url in (
        reverse("download-request-list"),
        reverse("company-download-list", args=[request.company_id]),
        reverse("company-detail", args=[request.company_id]),
        reverse("dashboard"),
    ):
        response = client.get(url)
        assert response.status_code == 200
        assert detail not in response.content.decode()
    assert DownloadRequest.objects.filter(pk=request.pk).exists()


def test_operator_sees_no_admin_actions(client, lifecycle_request, lifecycle_admin):
    OfficeMembership.objects.filter(user=lifecycle_admin).update(role="operator")
    client.force_login(lifecycle_admin)
    html = client.get(
        reverse("download-request-detail", args=[lifecycle_request.pk])
    ).content.decode()
    assert "Cancelar pedido" not in html
    assert "Excluir pedido" not in html


def test_cancel_action_has_csrf_protection(lifecycle_request, lifecycle_admin):
    client = Client(enforce_csrf_checks=True)
    client.force_login(lifecycle_admin)
    response = client.post(
        reverse("download-request-cancel", args=[lifecycle_request.pk]),
        {"note": "Sem CSRF", "confirm": "on"},
    )
    assert response.status_code == 403


def test_old_resolution_url_cannot_change_cancelled_request(
    client, lifecycle_request, lifecycle_admin
):
    cancel_download_request(
        lifecycle_request.pk,
        actor_id=lifecycle_admin.pk,
        note="Encerrado",
        acknowledge_remote_uncertainty=True,
    )
    client.force_login(lifecycle_admin)
    part = lifecycle_request.parts.first()
    response = client.post(
        reverse("download-result-resolve", args=[part.pk]),
        {"abandon": "on", "acknowledge": "on", "note": "Decisão antiga"},
    )
    assert response.status_code == 404
    part.refresh_from_db()
    assert part.status == "cancelled"
