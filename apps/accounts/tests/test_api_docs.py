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
