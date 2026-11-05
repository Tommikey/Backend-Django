"""Query counts must not grow with the number of students (or, for school-wide views, with the
number of classes). Each test measures a small school, grows it, and measures again."""

from types import SimpleNamespace

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.academics.models import Subject
from apps.assessments.models import Assessment, Submission
from apps.results.models import Score
from conftest import assign, enroll, make_classroom

pytestmark = pytest.mark.django_db


@pytest.fixture
def school_kit(school, term, make_user):
    """add_class() makes a class with two subjects and a quiz each; add_students(room, n) adds
    scored students who have submitted."""
    teacher = make_user("teacher")
    subjects = [Subject.objects.create(school=school, name=f"Subject {i}") for i in range(2)]
    components = list(school.score_split(term.session))

    def add_class():
        room = make_classroom(school, str(school.classrooms.count()))
        room.form_teacher = teacher
        room.save()
        for subject in subjects:
            assign(teacher, room, subject)
            Assessment.objects.create(
                title="Q", type="quiz", classroom=room, subject=subject, term=term, max_points=10
            )
        return room

    def add_students(room, n):
        quiz = room.assessments.first()
        for _ in range(n):
            student = make_user("student")
            enroll(student, room)
            Submission.objects.create(assessment=quiz, student=student, score=5)
            Score.objects.bulk_create(
                Score(student=student, subject=s, term=term, component=c, value=5)
                for s in subjects
                for c in components
            )

    return SimpleNamespace(add_class=add_class, add_students=add_students)


def count(client, method, url, data=None):
    with CaptureQueriesContext(connection) as queries:
        r = getattr(client, method)(url, data or {})
    assert r.status_code in (200, 201), r.content[:300]
    return len(queries)


@pytest.mark.parametrize("url", ["/api/v1/stats/", "/api/v1/academics/progress/"])
def test_school_wide_views_do_not_grow_with_classes(auth, admin_user, school_kit, url):
    client = auth(admin_user)
    for _ in range(2):
        school_kit.add_students(school_kit.add_class(), 2)
    small = count(client, "get", url)
    for _ in range(3):
        school_kit.add_students(school_kit.add_class(), 4)
    assert count(client, "get", url) == small


@pytest.mark.parametrize(
    "url",
    [
        "/api/v1/results/class-results/",
        "/api/v1/attendance/summary/",
        "/api/v1/results/score-sheet/",
    ],
)
def test_class_views_do_not_grow_with_students(auth, admin_user, school_kit, url):
    client = auth(admin_user)
    room = school_kit.add_class()
    school_kit.add_students(room, 2)
    params = {"classroom": room.pk, "subject": room.teaching_assignments.first().subject_id}
    small = count(client, "get", url, params)
    school_kit.add_students(room, 6)
    assert count(client, "get", url, params) == small


def test_publishing_costs_per_class_not_per_student(auth, admin_user, school_kit):
    client = auth(admin_user)
    rooms = [school_kit.add_class() for _ in range(2)]
    for room in rooms:
        school_kit.add_students(room, 1)
    small = count(client, "post", "/api/v1/results/publish/")

    client.post("/api/v1/results/unpublish/")
    for room in rooms:  # the same classes, five times the students
        school_kit.add_students(room, 4)
    # republishing both updates existing cards and creates new ones: one extra statement a
    # class, never one a student
    assert count(client, "post", "/api/v1/results/publish/") <= small + len(rooms)
