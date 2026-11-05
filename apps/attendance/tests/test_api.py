"""The attendance endpoints: who takes the register, how days are counted, locking with
published results, and attendance on report cards."""

from datetime import date, timedelta

import pytest

from apps.academics.models import Classroom
from apps.accounts.models import Guardianship
from apps.attendance.models import AttendanceRecord
from conftest import enroll, make_classroom

pytestmark = pytest.mark.django_db

REGISTER_URL = "/api/v1/attendance/register/"
SUMMARY_URL = "/api/v1/attendance/summary/"
STUDENT_URL = "/api/v1/attendance/student/"
CARD_URL = "/api/v1/results/report-card/"
PUBLISH_URL = "/api/v1/results/publish/"
UNPUBLISH_URL = "/api/v1/results/unpublish/"
SHEET_URL = "/api/v1/results/score-sheet/"

DAY1 = date(2025, 10, 6)
DAY2 = date(2025, 10, 7)
DAY3 = date(2025, 10, 8)


@pytest.fixture
def form_kit(kit, make_user):
    """`kit` with the teacher as JSS1A's form teacher and a second student in the class."""
    kit.classroom.form_teacher = kit.teacher
    kit.classroom.save()
    kit.classmate = make_user("student")
    enroll(kit.classmate, kit.classroom)
    return kit


def take(auth, kit, day, user=None, **marks):
    """marks: student attr name on kit -> status (or (status, note))."""
    body = {"classroom": kit.classroom.pk, "date": day.isoformat(), "marks": []}
    for name, value in marks.items():
        status, note = value if isinstance(value, tuple) else (value, "")
        body["marks"].append({"student": getattr(kit, name).pk, "status": status, "note": note})
    return auth(user or kit.teacher).put(REGISTER_URL, body, format="json")


# --- taking the register ---------------------------------------------------------------------


def test_form_teacher_takes_and_corrects_the_register(auth, form_kit):
    kit = form_kit
    r = take(auth, kit, DAY1, student="present", classmate=("absent", "Sick"))
    assert r.status_code == 200, r.content
    data = r.json()
    assert data["taken"] is True and data["can_edit"] is True
    by_id = {row["student"]["id"]: row for row in data["rows"]}
    assert by_id[kit.student.pk]["status"] == "present"
    assert by_id[kit.classmate.pk] == {
        "student": by_id[kit.classmate.pk]["student"],
        "status": "absent",
        "note": "Sick",
    }

    # correcting one student leaves the other alone; null clears
    take(auth, kit, DAY1, classmate="late")
    take(auth, kit, DAY1, student=None)
    r = auth(kit.teacher).get(REGISTER_URL, {"classroom": kit.classroom.pk, "date": DAY1})
    by_id = {row["student"]["id"]: row["status"] for row in r.json()["rows"]}
    assert by_id == {kit.student.pk: None, kit.classmate.pk: "late"}
    assert AttendanceRecord.objects.count() == 1


def test_untaken_register_lists_the_class(auth, form_kit):
    r = auth(form_kit.teacher).get(REGISTER_URL, {"classroom": form_kit.classroom.pk, "date": DAY1})
    assert r.status_code == 200
    assert r.json()["taken"] is False
    assert {row["status"] for row in r.json()["rows"]} == {None}
    assert len(r.json()["rows"]) == 2


def test_only_form_teacher_or_admin_takes_the_register(auth, form_kit, admin_user):
    kit = form_kit
    assert take(auth, kit, DAY1, user=admin_user, student="present").status_code == 200
    for user in (kit.other_teacher, kit.student):
        assert take(auth, kit, DAY1, user=user, student="absent").status_code == 403
        query = {"classroom": kit.classroom.pk, "date": DAY1}
        assert auth(user).get(REGISTER_URL, query).status_code == 403
        assert auth(user).get(SUMMARY_URL, {"classroom": kit.classroom.pk}).status_code == 403


def test_subject_teacher_who_is_not_form_teacher_cannot_take_it(auth, kit):
    # kit.teacher teaches Mathematics to the class but isn't its form teacher
    assert take(auth, kit, DAY1, student="present").status_code == 403


def test_register_validation(auth, form_kit):
    kit = form_kit
    assert take(auth, kit, DAY1, outsider="present").status_code == 400  # not in the class
    future = date.today() + timedelta(days=1)
    r = take(auth, kit, future, student="present")
    assert r.status_code == 400 and "ahead" in str(r.json())
    bad = take(auth, kit, DAY1, student="asleep")
    assert bad.status_code == 400

    twice = {
        "classroom": kit.classroom.pk,
        "date": DAY1.isoformat(),
        "marks": [
            {"student": kit.student.pk, "status": "present"},
            {"student": kit.student.pk, "status": "absent"},
        ],
    }
    assert auth(kit.teacher).put(REGISTER_URL, twice, format="json").status_code == 400

    empty = {"classroom": kit.classroom.pk, "date": DAY1.isoformat(), "marks": []}
    assert auth(kit.teacher).put(REGISTER_URL, empty, format="json").status_code == 400


def test_date_must_fall_inside_the_term(auth, form_kit):
    kit = form_kit
    kit.term.starts_on, kit.term.ends_on = date(2025, 9, 8), date(2025, 12, 12)
    kit.term.save()
    assert take(auth, kit, date(2025, 9, 5), student="present").status_code == 400
    assert take(auth, kit, DAY1, student="present").status_code == 200


def test_a_day_belongs_to_one_term(auth, form_kit):
    kit = form_kit
    take(auth, kit, DAY1, student="present")
    second_term = kit.session.terms.get(order=2)
    body = {
        "classroom": kit.classroom.pk,
        "date": DAY1.isoformat(),
        "term": second_term.pk,
        "marks": [{"student": kit.student.pk, "status": "absent"}],
    }
    r = auth(kit.teacher).put(REGISTER_URL, body, format="json")
    assert r.status_code == 400 and "another term" in str(r.json())


def test_another_schools_class_looks_missing(auth, form_kit, other_school, make_user):
    theirs = Classroom.objects.create(
        school=other_school, level=other_school.levels.order_by("order").first(), arm="A"
    )
    r = auth(form_kit.teacher).get(REGISTER_URL, {"classroom": theirs.pk, "date": DAY1})
    assert r.status_code == 400 and "classroom" in r.json()

    their_admin = make_user("admin", school=other_school)
    r = auth(their_admin).get(STUDENT_URL, {"student": form_kit.student.pk})
    assert r.status_code == 400 and "student" in r.json()


# --- counting --------------------------------------------------------------------------------


def test_class_summary_counts(auth, form_kit):
    kit = form_kit
    take(auth, kit, DAY1, student="present", classmate="absent")
    take(auth, kit, DAY2, student="late", classmate="excused")
    take(auth, kit, DAY3, student="absent")  # classmate not marked that day

    r = auth(kit.teacher).get(SUMMARY_URL, {"classroom": kit.classroom.pk})
    assert r.status_code == 200
    data = r.json()
    assert data["register_dates"] == [d.isoformat() for d in (DAY1, DAY2, DAY3)]
    rows = {row["student"]["id"]: row for row in data["rows"]}
    assert {k: rows[kit.student.pk][k] for k in ("days_open", "present", "late", "absent")} == {
        "days_open": 3,
        "present": 2,
        "late": 1,
        "absent": 1,
    }
    assert rows[kit.classmate.pk]["excused"] == 1
    assert rows[kit.classmate.pk]["absent"] == 1
    assert rows[kit.classmate.pk]["unmarked"] == 1


def test_days_open_is_per_class(auth, form_kit, make_user, school):
    kit = form_kit
    other_class = make_classroom(school, "B")
    other_class.form_teacher = kit.teacher
    other_class.save()
    pupil = make_user("student")
    enroll(pupil, other_class)
    take(auth, kit, DAY1, student="present")
    body = {
        "classroom": other_class.pk,
        "date": DAY2.isoformat(),
        "marks": [{"student": pupil.pk, "status": "present"}],
    }
    auth(kit.teacher).put(REGISTER_URL, body, format="json")

    r = auth(kit.teacher).get(SUMMARY_URL, {"classroom": kit.classroom.pk})
    assert r.json()["register_dates"] == [DAY1.isoformat()]


# --- a student's own view ---------------------------------------------------------------------


def test_student_attendance_readers(auth, form_kit, admin_user, make_user):
    kit = form_kit
    take(auth, kit, DAY1, student=("absent", "Dentist"))
    parent = make_user("parent")
    Guardianship.objects.create(parent=parent, student=kit.student)
    stranger_parent = make_user("parent")

    me = auth(kit.student).get(STUDENT_URL)  # a student may omit ?student=
    assert me.status_code == 200
    assert me.json()["summary"]["absent"] == 1
    assert me.json()["marks"] == [{"date": DAY1.isoformat(), "status": "absent", "note": "Dentist"}]

    query = {"student": kit.student.pk}
    for reader in (parent, kit.teacher, admin_user):
        assert auth(reader).get(STUDENT_URL, query).status_code == 200
    for outsider in (stranger_parent, kit.classmate, kit.other_teacher):
        assert auth(outsider).get(STUDENT_URL, query).status_code == 404
    assert auth(admin_user).get(STUDENT_URL).status_code == 404  # staff must name the student


# --- report cards and locking -----------------------------------------------------------------


def test_report_card_attendance_draft_and_published(auth, form_kit, admin_user):
    kit = form_kit
    query = {"student": kit.student.pk}
    card = auth(admin_user).get(CARD_URL, query).json()
    assert card["attendance"] is None  # no register taken yet

    take(auth, kit, DAY1, student="present", classmate="absent")
    take(auth, kit, DAY2, student="absent", classmate="present")
    card = auth(admin_user).get(CARD_URL, query).json()
    assert card["published"] is False
    assert card["attendance"]["days_open"] == 2 and card["attendance"]["present"] == 1

    assert auth(admin_user).post(PUBLISH_URL, {}).status_code == 202
    card = auth(kit.student).get(CARD_URL).json()
    assert card["published"] is True
    assert card["attendance"] == {
        "days_open": 2,
        "present": 1,
        "late": 0,
        "absent": 1,
        "excused": 0,
        "unmarked": 0,
    }


def test_publishing_locks_the_register(auth, form_kit, admin_user):
    kit = form_kit
    take(auth, kit, DAY1, student="present")
    auth(admin_user).post(PUBLISH_URL, {})

    r = take(auth, kit, DAY1, student="absent")
    assert r.status_code == 409
    query = {"classroom": kit.classroom.pk, "date": DAY1}
    assert auth(kit.teacher).get(REGISTER_URL, query).json()["can_edit"] is False

    # unpublishing reopens it; the next publish picks up the correction
    auth(admin_user).post(UNPUBLISH_URL, {})
    assert take(auth, kit, DAY1, student="absent").status_code == 200
    auth(admin_user).post(PUBLISH_URL, {})
    card = auth(kit.student).get(CARD_URL).json()
    assert card["attendance"]["absent"] == 1


def test_register_blocks_deleting_a_class(auth, form_kit, admin_user):
    kit = form_kit
    take(auth, kit, DAY1, student="present")
    r = auth(admin_user).delete(f"/api/v1/academics/classrooms/{kit.classroom.pk}/")
    assert r.status_code == 409


def test_attendance_outlives_the_enrollment(auth, form_kit, admin_user):
    kit = form_kit
    take(auth, kit, DAY1, student="absent")
    kit.student.enrollments.all().delete()
    for reader in (kit.student, kit.teacher, admin_user):
        r = auth(reader).get(STUDENT_URL, {"student": kit.student.pk})
        assert r.status_code == 200, (reader.role, r.content)
        assert r.json()["summary"]["absent"] == 1
    assert auth(kit.other_teacher).get(STUDENT_URL, {"student": kit.student.pk}).status_code == 404
