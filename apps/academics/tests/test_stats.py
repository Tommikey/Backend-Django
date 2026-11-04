import pytest

from apps.academics.services import create_session
from apps.assessments.models import Assessment, Submission
from conftest import enroll, make_classroom

pytestmark = pytest.mark.django_db


@pytest.fixture
def scored_quiz(kit):
    quiz = Assessment.objects.create(
        title="Q",
        type="quiz",
        classroom=kit.classroom,
        subject=kit.subject,
        term=kit.term,
        created_by=kit.teacher,
        max_points=2,
    )
    Submission.objects.create(assessment=quiz, student=kit.student, score=1)
    return quiz


def test_stats_admin_only(auth, kit):
    assert auth(kit.teacher).get("/api/v1/stats/").status_code == 403
    assert auth(kit.student).get("/api/v1/stats/").status_code == 403


def test_stats_unauthenticated(api):
    assert api.get("/api/v1/stats/").status_code == 401


def test_stats_counts(auth, kit, scored_quiz, admin_user):
    data = auth(admin_user).get("/api/v1/stats/").json()
    assert data["counts"] == {
        "students": 2,  # kit.student + kit.outsider
        "teachers": 2,  # kit.teacher + kit.other_teacher
        "parents": 0,
        "classrooms": 1,
        "lessons": 0,
        "assessments": 1,
        "submissions": 1,
        "live_classes": 0,
    }
    [row] = data["classrooms"]
    assert row["name"] == "JSS1A"
    assert row["students"] == 1
    assert row["avg_score_pct"] == 50.0


def test_stats_class_size_is_for_the_current_session(auth, kit, admin_user):
    last_year = create_session(kit.school, "2024/2025")
    enroll(kit.outsider, kit.classroom, session=last_year)
    make_classroom(kit.school, "B")
    rows = {
        c["name"]: c["students"]
        for c in auth(admin_user).get("/api/v1/stats/").json()["classrooms"]
    }
    assert rows == {"JSS1A": 1, "JSS1B": 0}
