from contextlib import contextmanager
from io import StringIO
from types import SimpleNamespace

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError


def test_probe_default_does_not_submit_queries(monkeypatch):
    @contextmanager
    def open_client(company_id):
        yield SimpleNamespace(list_messages=lambda: SimpleNamespace(items=()))

    monkeypatch.setattr(
        "apps.fiscal.management.commands.probe_atf_pb.open_atf_client", open_client
    )
    output = StringIO()
    call_command("probe_atf_pb", "--company-id", "1", stdout=output)
    assert "A1 autenticado" in output.getvalue()


def test_probe_submission_requires_explicit_actor_and_period():
    with pytest.raises(CommandError):
        call_command("probe_atf_pb", "--company-id", "1", "--submit")
