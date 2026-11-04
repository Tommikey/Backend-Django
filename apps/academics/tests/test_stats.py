import pytest

from apps.academics.models import Classroom, Enrollment, Subject
from apps.assessments.models import Assessment, Submission

pytestmark = pytest.mark.django_db


@pytest.fixture
def stats_data(make_user, school):
    teacher = make_user("teacher")
    student = make_user("student")
    classroom = Classroom.objects.create(school=school, name="8A", created_by=teacher)
    Enrollment.objects.create(classroom=classroom, student=student)
    subject = Subject.objects.create(school=school, name="Math")
    quiz = Assessment.objects.create(
        title="Q", type="quiz", classroom=classroom, subject=subject, created_by=teacher, max_points=2
    )
    Submission.objects.create(assessment=quiz, student=student, score=1, graded_at=None)
    return teacher, student, classroom


def test_stats_admin_only(api, auth, stats_data, make_user):
    teacher, _, _ = stats_data
    assert auth(teacher).get("/api/v1/stats/").status_code == 403
    student = make_user("student")
    assert auth(student).get("/api/v1/stats/").status_code == 403


def test_stats_counts(api, auth, stats_data, admin_user):
    teacher, student, classroom = stats_data
    data = auth(admin_user).get("/api/v1/stats/").json()
    assert data["counts"] == {
        "students": 1,
        "teachers": 1,
        "parents": 0,
        "classrooms": 1,
        "lessons": 0,
        "assessments": 1,
        "submissions": 1,
        "sessions": 0,
    }
    assert data["classrooms"][0]["name"] == "8A"
    assert data["classrooms"][0]["students"] == 1
    assert data["classrooms"][0]["avg_score_pct"] == 50.0


def test_stats_unauthenticated(api):
    assert api.get("/api/v1/stats/").status_code == 401
