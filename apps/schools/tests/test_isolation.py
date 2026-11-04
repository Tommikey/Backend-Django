"""Tenant isolation: nothing belonging to another school is visible, reachable or linkable."""

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.academics.models import Classroom, Enrollment, Lesson, Subject
from apps.accounts.models import Guardianship
from apps.assessments.models import Assessment, Submission
from apps.sessions.models import StudySession
from conftest import results

pytestmark = pytest.mark.django_db


@pytest.fixture
def theirs(make_user, other_school):
    """A full set of records in the other school."""
    teacher = make_user("teacher", school=other_school)
    student = make_user("student", school=other_school)
    parent = make_user("parent", school=other_school)
    subject = Subject.objects.create(school=other_school, name="Physics")
    classroom = Classroom.objects.create(school=other_school, name="Year 9A", created_by=teacher)
    enrollment = Enrollment.objects.create(classroom=classroom, student=student)
    lesson = Lesson.objects.create(
        title="Forces", classroom=classroom, subject=subject, created_by=teacher
    )
    assessment = Assessment.objects.create(
        title="Essay", type="assignment", classroom=classroom, subject=subject, created_by=teacher
    )
    submission = Submission.objects.create(assessment=assessment, student=student, text="hi")
    session = StudySession.objects.create(
        title="Revision",
        classroom=classroom,
        starts_at=timezone.now() + timedelta(days=1),
        join_url="https://meet.jit.si/x",
        hosted_by=teacher,
    )
    link = Guardianship.objects.create(parent=parent, student=student)
    return {
        "teacher": teacher,
        "student": student,
        "parent": parent,
        "subject": subject,
        "classroom": classroom,
        "level": other_school.levels.first(),
        "urls": {
            "users": f"/api/v1/users/{student.pk}/",
            "guardianships": f"/api/v1/guardianships/{link.pk}/",
            "schools/levels": f"/api/v1/schools/levels/{other_school.levels.first().pk}/",
            "academics/subjects": f"/api/v1/academics/subjects/{subject.pk}/",
            "academics/classrooms": f"/api/v1/academics/classrooms/{classroom.pk}/",
            "academics/enrollments": f"/api/v1/academics/enrollments/{enrollment.pk}/",
            "academics/lessons": f"/api/v1/academics/lessons/{lesson.pk}/",
            "assessments": f"/api/v1/assessments/{assessment.pk}/",
            "submissions": f"/api/v1/submissions/{submission.pk}/",
            "sessions": f"/api/v1/sessions/{session.pk}/",
        },
    }


RESOURCES = [
    "users",
    "guardianships",
    "schools/levels",
    "academics/subjects",
    "academics/classrooms",
    "academics/enrollments",
    "academics/lessons",
    "assessments",
    "submissions",
    "sessions",
]


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
    # submissions can't be deleted by anyone (405); everything else must 404
    assert client.delete(url).status_code == (405 if resource == "submissions" else 404)


def test_cannot_point_at_another_schools_classroom_or_subject(auth, school, make_user, theirs):
    teacher = make_user("teacher")
    mine = Classroom.objects.create(school=school, name="JSS1A", created_by=teacher)
    my_subject = Subject.objects.create(school=school, name="Maths")
    client = auth(teacher)
    r = client.post(
        "/api/v1/academics/lessons/",
        {"title": "Sneaky", "classroom": theirs["classroom"].pk, "subject": my_subject.pk},
    )
    assert r.status_code == 400 and "classroom" in r.json()
    r = client.post(
        "/api/v1/academics/lessons/",
        {"title": "Sneaky", "classroom": mine.pk, "subject": theirs["subject"].pk},
    )
    assert r.status_code == 400 and "subject" in r.json()
    assert not Lesson.objects.filter(title="Sneaky").exists()


def test_other_schools_ids_look_like_missing_ids(auth, school, make_user, theirs):
    """Same error for "belongs to another school" as for "doesn't exist": nothing leaks."""
    teacher = make_user("teacher")
    mine = Classroom.objects.create(school=school, name="JSS1A", created_by=teacher)
    client = auth(teacher)
    other = client.post(
        "/api/v1/academics/enrollments/",
        {"classroom": mine.pk, "student": theirs["student"].pk},
    ).json()
    missing = client.post(
        "/api/v1/academics/enrollments/", {"classroom": mine.pk, "student": 999999}
    ).json()
    assert other["student"][0].replace(str(theirs["student"].pk), "N") == missing["student"][
        0
    ].replace("999999", "N")


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
    r = client.post("/api/v1/academics/classrooms/", {"name": "Year 9A"})
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
    assert auth(admin_user).get("/api/v1/academics/progress/").json() == {"classrooms": []}


def test_platform_staff_see_no_school_data(auth, theirs, db):
    from apps.accounts.models import User

    staff = User.objects.create_superuser(username="ops", email="o@x.com", password="x")
    assert results(auth(staff).get("/api/v1/academics/classrooms/").json()) == []
