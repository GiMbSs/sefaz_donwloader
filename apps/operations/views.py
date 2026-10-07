from django.db import DatabaseError, connection
from django.http import HttpRequest, JsonResponse
from django.shortcuts import render


def home(request: HttpRequest):
    return render(request, "operations/home.html")


def health(request: HttpRequest) -> JsonResponse:
    """Minimal readiness endpoint that verifies database reachability."""
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except DatabaseError:
        return JsonResponse({"status": "unavailable"}, status=503)
    return JsonResponse({"status": "ok"})

