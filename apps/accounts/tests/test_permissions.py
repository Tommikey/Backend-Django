"""Cross-app permission rules: login required everywhere, and owner-only edits."""

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.academics.models import Classroom, Lesson, Subject
from apps.assessments.models import Assessment
from apps.sessions.models import StudySession

pytestmark = pytest.mark.django_db

PROTECTED_LIST_URLS = [
    "/api/v1/academics/subjects/",
    "/api/v1/academics/classrooms/",
    "/api/v1/academics/enrollments/",
    "/api/v1/academics/lessons/",
    "/api/v1/academics/progress/",
    "/api/v1/assessments/",
    "/api/v1/submissions/",
    "/api/v1/sessions/",
    "/api/v1/stats/",
]


@pytest.mark.parametrize("url", PROTECTED_LIST_URLS)
def test_anonymous_gets_401_not_500(api, url):
    r = api.get(url)
    assert r.status_code == 401, (url, r.status_code)


@pytest.fixture
def owned(make_user, school):
    """One object of each owned kind, all belonging to `owner`."""
    owner = make_user("teacher")
    other = make_user("teacher")
    subject = Subject.objects.create(school=school, name="Math")
    classroom = Classroom.objects.create(school=school, name="8A", created_by=owner)
    lesson = Lesson.objects.create(
        title="Fractions", classroom=classroom, subject=subject, created_by=owner
    )
    assessment = Assessment.objects.create(
        title="Quiz 1", type="quiz", classroom=classroom, subject=subject, created_by=owner
    )
    session = StudySession.objects.create(
        title="Revision",
        classroom=classroom,
        starts_at=timezone.now() + timedelta(days=1),
        join_url="https://meet.jit.si/yap-revision",
        hosted_by=owner,
    )
    urls = {
        "classroom": f"/api/v1/academics/classrooms/{classroom.pk}/",
        "lesson": f"/api/v1/academics/lessons/{lesson.pk}/",
        "assessment": f"/api/v1/assessments/{assessment.pk}/",
        "session": f"/api/v1/sessions/{session.pk}/",
    }
    return owner, other, urls


KINDS = ["classroom", "lesson", "assessment", "session"]
EDIT = {
    "classroom": {"description": "edited"},
    "lesson": {"content": "edited"},
    "assessment": {"description": "edited"},
    "session": {"description": "edited"},
}


@pytest.mark.parametrize("kind", KINDS)
def test_other_teacher_cannot_edit_or_delete(auth, owned, kind):
    _, other, urls = owned
    client = auth(other)
    assert client.patch(urls[kind], EDIT[kind], format="json").status_code == 403
    assert client.delete(urls[kind]).status_code == 403
    # still readable: visibility is unchanged, only writes are owner-only
    assert client.get(urls[kind]).status_code == 200


@pytest.mark.parametrize("kind", KINDS)
def test_owner_can_edit_and_delete(auth, owned, kind):
    owner, _, urls = owned
    client = auth(owner)
    r = client.patch(urls[kind], EDIT[kind], format="json")
    assert r.status_code == 200, r.content
    assert client.delete(urls[kind]).status_code == 204


@pytest.mark.parametrize("kind", KINDS)
def test_admin_can_edit_and_delete_anything(auth, owned, admin_user, kind):
    _, _, urls = owned
    client = auth(admin_user)
    r = client.patch(urls[kind], EDIT[kind], format="json")
    assert r.status_code == 200, r.content
    assert client.delete(urls[kind]).status_code == 204
