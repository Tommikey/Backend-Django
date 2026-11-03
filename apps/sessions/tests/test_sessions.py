from datetime import timedelta

import pytest
from django.utils import timezone

from apps.academics.models import Classroom, Enrollment
from apps.sessions.models import StudySession
from conftest import results

pytestmark = pytest.mark.django_db


@pytest.fixture
def setup(make_user):
    teacher = make_user("teacher")
    student = make_user("student")
    outsider = make_user("student")
    classroom = Classroom.objects.create(name="8A", created_by=teacher)
    Enrollment.objects.create(classroom=classroom, student=student)
    return teacher, student, outsider, classroom


def session_payload(classroom, **overrides):
    base = {
        "title": "Algebra revision",
        "classroom": classroom.pk,
        "starts_at": (timezone.now() + timedelta(days=1)).isoformat(),
        "join_url": "https://meet.jit.si/yap-algebra",
    }
    return {**base, **overrides}


def test_teacher_creates_session(api, auth, setup):
    teacher, _, _, classroom = setup
    r = auth(teacher).post("/api/v1/sessions/", session_payload(classroom))
    assert r.status_code == 201, r.content
    assert StudySession.objects.get(pk=r.data["id"]).hosted_by == teacher


def test_student_sees_only_enrolled_sessions(api, auth, setup):
    teacher, student, outsider, classroom = setup
    StudySession.objects.create(
        title="S", classroom=classroom, hosted_by=teacher,
        starts_at=timezone.now(), join_url="https://x.example/j",
    )
    assert len(results(auth(student).get("/api/v1/sessions/").json())) == 1
    assert results(auth(outsider).get("/api/v1/sessions/").json()) == []
    assert len(results(auth(teacher).get("/api/v1/sessions/").json())) == 1


def test_student_cannot_create_session(api, auth, setup):
    _, student, _, classroom = setup
    assert auth(student).post("/api/v1/sessions/", session_payload(classroom)).status_code == 403


def test_upcoming_filter(api, auth, setup):
    teacher, student, _, classroom = setup
    StudySession.objects.create(
        title="Past", classroom=classroom, hosted_by=teacher,
        starts_at=timezone.now() - timedelta(days=1), join_url="https://x.example/p",
    )
    StudySession.objects.create(
        title="Future", classroom=classroom, hosted_by=teacher,
        starts_at=timezone.now() + timedelta(days=1), join_url="https://x.example/f",
    )
    upcoming = results(auth(student).get("/api/v1/sessions/?upcoming=1").json())
    assert [s["title"] for s in upcoming] == ["Future"]
