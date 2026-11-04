"""Tenant isolation: nothing belonging to another school is visible, reachable or linkable."""

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.academics.models import Lesson, Subject
from apps.accounts.models import Guardianship
from apps.assessments.models import Assessment, Submission
from apps.sessions.models import StudySession
from conftest import assign, enroll, make_classroom, results

pytestmark = pytest.mark.django_db


@pytest.fixture
def theirs(make_user, other_school):
    """A full set of records in the other school."""
    teacher = make_user("teacher", school=other_school)
    student = make_user("student", school=other_school)
    parent = make_user("parent", school=other_school)
    session = other_school.academic_sessions.get(is_current=True)
    term = session.terms.get(is_current=True)
    subject = Subject.objects.create(school=other_school, name="Physics")
    classroom = make_classroom(other_school, "A", level_order=3)  # Year 9A
    assignment = assign(teacher, classroom, subject)
    enrollment = enroll(student, classroom)
    in_class = {"classroom": classroom, "subject": subject, "term": term}
    lesson = Lesson.objects.create(title="Forces", created_by=teacher, **in_class)
    assessment = Assessment.objects.create(
        title="Essay", type="assignment", created_by=teacher, **in_class
    )
    submission = Submission.objects.create(assessment=assessment, student=student, text="hi")
    live = StudySession.objects.create(
        title="Revision",
        starts_at=timezone.now() + timedelta(days=1),
        join_url="https://meet.jit.si/x",
        hosted_by=teacher,
        **in_class,
    )
    link = Guardianship.objects.create(parent=parent, student=student)
    return {
        "teacher": teacher,
        "student": student,
        "parent": parent,
        "subject": subject,
        "classroom": classroom,
        "term": term,
        "session": session,
        "urls": {
            "users": f"/api/v1/users/{student.pk}/",
            "guardianships": f"/api/v1/guardianships/{link.pk}/",
            "schools/levels": f"/api/v1/schools/levels/{classroom.level_id}/",
            "academics/academic-sessions": f"/api/v1/academics/academic-sessions/{session.pk}/",
            "academics/terms": f"/api/v1/academics/terms/{term.pk}/",
            "academics/subjects": f"/api/v1/academics/subjects/{subject.pk}/",
            "academics/classrooms": f"/api/v1/academics/classrooms/{classroom.pk}/",
            "academics/teaching-assignments": (
                f"/api/v1/academics/teaching-assignments/{assignment.pk}/"
            ),
            "academics/enrollments": f"/api/v1/academics/enrollments/{enrollment.pk}/",
            "academics/lessons": f"/api/v1/academics/lessons/{lesson.pk}/",
            "assessments": f"/api/v1/assessments/{assessment.pk}/",
            "submissions": f"/api/v1/submissions/{submission.pk}/",
            "sessions": f"/api/v1/sessions/{live.pk}/",
        },
    }


RESOURCES = [
    "users",
    "guardianships",
    "schools/levels",
    "academics/academic-sessions",
    "academics/terms",
    "academics/subjects",
    "academics/classrooms",
    "academics/teaching-assignments",
    "academics/enrollments",
    "academics/lessons",
    "assessments",
    "submissions",
    "sessions",
]
# endpoints without a delete action answer 405 to DELETE whatever the object
NO_DELETE = {"submissions", "academics/terms"}


@pytest.mark.parametrize("resource", RESOURCES)
def test_lists_never_show_other_schools_rows(auth, admin_user, theirs, resource):
    rows = results(auth(admin_user).get(f"/api/v1/{resource}/").json())
    other_ids = {int(theirs["urls"][resource].rstrip("/").rsplit("/", 1)[1])}
    assert not other_ids & {row["id"] for row in rows}


@pytest.mark.parametrize("resource", RESOURCES)
def test_other_schools_rows_are_404_even_for_admins(auth, admin_user, theirs, resource):
    client = auth(admin_user)
    url = theirs["urls"][resource]
    assert client.get(url).status_code == 404
    assert client.patch(url, {}, format="json").status_code == 404
    assert client.delete(url).status_code == (405 if resource in NO_DELETE else 404)


def test_cannot_point_lessons_at_another_schools_records(auth, kit, theirs):
    client = auth(kit.teacher)
    base = {"title": "Sneaky", "classroom": kit.classroom.pk, "subject": kit.subject.pk}
    for field in ("classroom", "subject", "term"):
        r = client.post("/api/v1/academics/lessons/", {**base, field: theirs[field].pk})
        assert r.status_code == 400 and field in r.json(), (field, r.content)
    assert not Lesson.objects.filter(title="Sneaky").exists()


def test_cannot_set_up_with_another_schools_records(auth, admin_user, kit, theirs):
    client = auth(admin_user)
    r = client.post(
        "/api/v1/academics/teaching-assignments/",
        {"classroom": kit.classroom.pk, "subject": kit.subject.pk, "teacher": theirs["teacher"].pk},
    )
    assert r.status_code == 400 and "teacher" in r.json()
    r = client.post(
        "/api/v1/academics/enrollments/",
        {"classroom": kit.classroom.pk, "student": kit.outsider.pk, "session": theirs["session"].pk},
    )
    assert r.status_code == 400 and "session" in r.json()
    r = client.post("/api/v1/academics/classrooms/", {"level": theirs["classroom"].level_id})
    assert r.status_code == 400 and "level" in r.json()


def test_other_schools_ids_look_like_missing_ids(auth, admin_user, kit, theirs):
    """Same error for "belongs to another school" as for "doesn't exist": nothing leaks."""
    client = auth(admin_user)
    url = "/api/v1/academics/enrollments/"
    other = client.post(url, {"classroom": kit.classroom.pk, "student": theirs["student"].pk})
    missing = client.post(url, {"classroom": kit.classroom.pk, "student": 999999})
    normalise = {str(theirs["student"].pk): "N", "999999": "N"}

    def message(response):
        text = response.json()["student"][0]
        for raw, placeholder in normalise.items():
            text = text.replace(raw, placeholder)
        return text

    assert message(other) == message(missing)


def test_cannot_link_another_schools_parent(auth, admin_user, make_user, theirs):
    my_student = make_user("student")
    r = auth(admin_user).post(
        "/api/v1/guardianships/", {"parent": theirs["parent"].pk, "student": my_student.pk}
    )
    assert r.status_code == 400 and "parent" in r.json()


def test_names_are_unique_per_school_not_globally(auth, admin_user, theirs):
    client = auth(admin_user)
    r = client.post("/api/v1/academics/subjects/", {"name": "Physics"})
    assert r.status_code == 201, r.content  # the other school also has "Physics"
    assert client.post("/api/v1/academics/subjects/", {"name": "physics"}).status_code == 400
    # both schools have a "2025/2026" session; a new name is free in each
    r = client.post("/api/v1/academics/academic-sessions/", {"name": "2026/2027"})
    assert r.status_code == 201, r.content


def test_stats_count_only_own_school(auth, admin_user, theirs):
    counts = auth(admin_user).get("/api/v1/stats/").json()["counts"]
    assert counts == {
        "students": 0,
        "teachers": 0,
        "parents": 0,
        "classrooms": 0,
        "lessons": 0,
        "assessments": 0,
        "submissions": 0,
        "sessions": 0,
    }


def test_progress_shows_only_own_school(auth, admin_user, theirs):
    assert auth(admin_user).get("/api/v1/academics/progress/").json()["classrooms"] == []


def test_platform_staff_see_no_school_data(auth, theirs, db):
    from apps.accounts.models import User

    staff = User.objects.create_superuser(username="ops", email="o@x.com", password="x")
    assert results(auth(staff).get("/api/v1/academics/classrooms/").json()) == []
