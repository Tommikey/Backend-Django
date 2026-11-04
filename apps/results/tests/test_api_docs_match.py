"""The documented response shapes (apps/*/openapi.py) match what the hand-built views return.

Each endpoint is called with real data and its JSON is walked against the OpenAPI schema:
every documented field is present, nothing undocumented appears, nulls only where allowed.
"""

import pytest

from apps.accounts.models import Guardianship
from conftest import check, response_schema

pytestmark = pytest.mark.django_db


@pytest.fixture
def filled(auth, kit, admin_user, make_user):
    """kit with marks, a comment, a register day, the teacher as form teacher, a parent."""
    kit.classroom.form_teacher = kit.teacher
    kit.classroom.save()
    comps = list(kit.school.components.order_by("order"))
    auth(kit.teacher).put(
        "/api/v1/results/score-sheet/",
        {
            "classroom": kit.classroom.pk,
            "subject": kit.subject.pk,
            "scores": [
                {"student": kit.student.pk, "component": comps[0].pk, "value": 15},
                {"student": kit.student.pk, "component": comps[2].pk, "value": 50},
            ],
        },
        format="json",
    )
    auth(kit.teacher).put(
        "/api/v1/attendance/register/",
        {
            "classroom": kit.classroom.pk,
            "date": "2025-10-06",
            "marks": [{"student": kit.student.pk, "status": "late", "note": "Bus"}],
        },
        format="json",
    )
    kit.parent = make_user("parent")
    Guardianship.objects.create(parent=kit.parent, student=kit.student)
    kit.admin = admin_user
    return kit


def test_handbuilt_responses_match_the_docs(spec, auth, filled):
    kit = filled
    admin = auth(kit.admin)
    calls = [
        ("results/score-sheet/", "get", {"classroom": kit.classroom.pk, "subject": kit.subject.pk}),
        ("results/report-card/", "get", {"student": kit.student.pk}),  # draft
        ("results/class-results/", "get", {"classroom": kit.classroom.pk}),
        ("attendance/register/", "get", {"classroom": kit.classroom.pk, "date": "2025-10-06"}),
        ("attendance/summary/", "get", {"classroom": kit.classroom.pk}),
        ("attendance/student/", "get", {"student": kit.student.pk}),
        ("stats/", "get", {}),
        ("academics/progress/", "get", {}),
        ("schools/components/", "get", {}),
        ("schools/grade-bands/", "get", {}),
    ]
    for path, method, params in calls:
        r = getattr(admin, method)(f"/api/v1/{path}", params)
        assert r.status_code == 200, (path, r.content[:200])
        check(spec, response_schema(spec, path, method, 200), r.json(), path)

    r = admin.put(
        "/api/v1/results/comments/",
        {"student": kit.student.pk, "principal_comment": "Good term."},
        format="json",
    )
    check(spec, response_schema(spec, "results/comments/", "put", 200), r.json(), "comments")

    r = admin.post("/api/v1/results/publish/", {})
    assert r.status_code == 201
    check(spec, response_schema(spec, "results/publish/", "post", 201), r.json(), "publish")
    r = auth(kit.parent).get("/api/v1/results/report-card/", {"student": kit.student.pk})
    check(spec, response_schema(spec, "results/report-card/", "get", 200), r.json(), "card")
    r = auth(kit.admin).post("/api/v1/results/unpublish/", {})  # auth() shares one client
    check(spec, response_schema(spec, "results/unpublish/", "post", 200), r.json(), "unpublish")


def test_auth_and_onboarding_responses_match_the_docs(spec, api, auth, make_user):
    from conftest import PASSWORD

    user = make_user("teacher")
    r = auth(user).post(
        "/api/v1/auth/password/",
        {"current_password": PASSWORD, "new_password": "Another-Strong-77"},
    )
    check(spec, response_schema(spec, "auth/password/", "post", 200), r.json(), "password")

    api.credentials()
    r = api.post(
        "/api/v1/schools/onboard/",
        {
            "school_name": "Docs Academy",
            "system": "uk",
            "admin": {"username": "docs_admin", "email": "d@x.org", "password": "Docs-Pass-2026!"},
        },
        format="json",
    )
    assert r.status_code == 201, r.content
    check(spec, response_schema(spec, "schools/onboard/", "post", 201), r.json(), "onboard")
