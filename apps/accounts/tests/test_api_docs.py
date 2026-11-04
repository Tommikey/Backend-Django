"""The API docs: the schema generates cleanly and the docs pages are reachable."""

import pytest
from django.core.management import call_command

pytestmark = pytest.mark.django_db


def test_schema_generates_without_warnings(tmp_path):
    # --fail-on-warn: an undocumented view or a name clash fails the build
    call_command("spectacular", "--validate", "--fail-on-warn", "--file", str(tmp_path / "s.yml"))


def test_docs_pages_are_public(api):
    assert api.get("/api/schema/").status_code == 200
    assert api.get("/api/docs/").status_code == 200


def test_health_check(api, settings):
    r = api.get("/healthz/")
    assert r.status_code == 200 and r.json() == {"status": "ok"}
    # exempt from the HTTPS redirect a load balancer would otherwise get
    settings.SECURE_SSL_REDIRECT = True
    settings.SECURE_REDIRECT_EXEMPT = [r"^healthz/$"]
    from rest_framework.test import APIClient

    fresh = APIClient()  # middleware reads its settings when a client first loads it
    assert fresh.get("/healthz/").status_code == 200
    assert fresh.get("/api/v1/auth/me/").status_code == 301


def test_health_check_reports_a_dead_database(api, monkeypatch):
    class DeadConnection:
        def cursor(self):
            raise RuntimeError("connection refused")

    monkeypatch.setattr("config.health.connection", DeadConnection())
    r = api.get("/healthz/")
    assert r.status_code == 503 and r.json()["database"] == "unreachable"
