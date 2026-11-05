"""The dashboard: each role gets its own block, built from live data, in few queries."""

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.accounts.models import Guardianship
from apps.assessments.models import Assessment, Submission
from apps.attendance.models import AttendanceRecord
from apps.live_classes.models import LiveClass
from conftest import check, enroll, response_schema

pytestmark = pytest.mark.django_db

URL = "/api/v1/dashboard/"


@pytest.fixture
def busy(kit):
    """kit with: the teacher as form teacher, an assignment due tomorrow (unsubmitted), an
    overdue one, a quiz the student submitted (graded), an essay submitted awaiting a grade,
    a live class tomorrow, and today's register not taken."""
    kit.classroom.form_teacher = kit.teacher
    kit.classroom.save()
    now = timezone.now()
    common = {"classroom": kit.classroom, "subject": kit.subject, "term": kit.term}

    def work(title, kind="assignment", due=None):
        return Assessment.objects.create(title=title, type=kind, due_at=due, **common)

    kit.due = work("Essay due", due=now + timedelta(days=1))
    kit.overdue = work("Late essay", due=now - timedelta(days=1))
    quiz = work("Quiz", kind="quiz")
    Submission.objects.create(assessment=quiz, student=kit.student, score=3)
    to_grade = work("Graded later")
    Submission.objects.create(assessment=to_grade, student=kit.student, text="mine")
    LiveClass.objects.create(
        title="Revision", starts_at=now + timedelta(days=1), join_url="https://x.org/j", **common
    )
    return kit


def get(auth, user, spec):
    r = auth(user).get(URL)
    assert r.status_code == 200, r.content
    data = r.json()
    check(spec, response_schema(spec, "dashboard/", "get", 200), data, "dashboard")
    return data


def test_student_dashboard(auth, busy, spec):
    data = get(auth, busy.student, spec)
    assert data["role"] == "student" and data["teacher"] is None
    block = data["student"]
    assert [w["title"] for w in block["due_work"]] == ["Essay due"]
    assert block["due_count"] == 1 and block["overdue_count"] == 1
    assert [lc["title"] for lc in block["upcoming_live_classes"]] == ["Revision"]
    assert block["attendance"] is None and block["latest_report_card"] is None


def test_teacher_dashboard(auth, busy, spec):
    data = get(auth, busy.teacher, spec)
    block = data["teacher"]
    assert block["registers"] == [
        {"classroom": {"id": busy.classroom.pk, "name": "JSS1A"}, "taken_today": False}
    ]
    assert block["to_grade_count"] == 1
    assert [a["title"] for a in block["to_grade"]] == ["Graded later"]
    assert len(block["upcoming_live_classes"]) == 1

    AttendanceRecord.objects.create(
        student=busy.student,
        classroom=busy.classroom,
        term=busy.term,
        date=timezone.localdate(),
        status="present",
    )
    assert get(auth, busy.teacher, spec)["teacher"]["registers"][0]["taken_today"] is True
    # a teacher with nothing assigned sees empty lists, not someone else's work
    other = get(auth, busy.other_teacher, spec)["teacher"]
    assert other == {
        "registers": [],
        "to_grade_count": 0,
        "to_grade": [],
        "upcoming_live_classes": [],
    }


def test_admin_dashboard(auth, busy, admin_user, spec):
    block = get(auth, admin_user, spec)["admin"]
    assert block["people"] == {"students": 2, "teachers": 2, "parents": 0}
    assert block["registers_missing_today"] == [
        {
            "classroom": {"id": busy.classroom.pk, "name": "JSS1A"},
            "form_teacher": busy.teacher.display_name,
        }
    ]
    assert block["term_status"]["published"] is False
    assert block["term_status"]["classes"] == 1


def test_parent_dashboard_after_publishing(auth, busy, admin_user, make_user, spec):
    parent = make_user("parent")
    Guardianship.objects.create(parent=parent, student=busy.student)
    AttendanceRecord.objects.create(
        student=busy.student,
        classroom=busy.classroom,
        term=busy.term,
        date=timezone.localdate() - timedelta(days=1),
        status="absent",
    )
    comp = busy.school.score_split(busy.session).first()
    from apps.results.models import Score

    Score.objects.create(
        student=busy.student, subject=busy.subject, term=busy.term, component=comp, value=15
    )
    assert auth(admin_user).post("/api/v1/results/publish/", {}).status_code == 201

    [child] = get(auth, parent, spec)["parent"]["children"]
    assert child["student"]["id"] == busy.student.pk
    assert child["classroom"]["name"] == "JSS1A"
    assert child["due_count"] == 1 and child["overdue_count"] == 1
    assert child["attendance"]["absent"] == 1
    assert child["latest_report_card"]["average"] == "15.00"


def test_query_counts_are_bounded(auth, busy, admin_user, make_user, django_assert_max_num_queries):
    for _ in range(6):  # a bigger class
        enroll(make_user("student"), busy.classroom)
    for user, limit in ((busy.student, 12), (busy.teacher, 10), (admin_user, 10)):
        with django_assert_max_num_queries(limit):
            assert auth(user).get(URL).status_code == 200
