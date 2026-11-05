"""The timetable: the school day's periods, each class's week, each teacher's week."""

from datetime import date, time
from unittest import mock

import pytest

from apps.academics.models import Subject
from apps.academics.services import create_session
from apps.accounts.models import Guardianship
from apps.audit.models import AuditEntry
from apps.schools.models import School
from apps.timetable.models import Period, Slot
from conftest import assign, make_classroom

pytestmark = pytest.mark.django_db

PERIODS_URL = "/api/v1/timetable/periods/"
CLASS_URL = "/api/v1/timetable/class/"
TEACHER_URL = "/api/v1/timetable/teacher/"
MONDAY = date(2026, 11, 2)


@pytest.fixture
def day(kit, make_user):
    """kit plus: periods 1-2, a break and period 3; English in JSS1A by a second teacher;
    JSS1B, where kit.teacher also teaches Mathematics."""
    p = {}
    for name, start, end, is_break in (
        ("Period 1", time(8), time(8, 40), False),
        ("Period 2", time(8, 40), time(9, 20), False),
        ("Break", time(9, 20), time(9, 40), True),
        ("Period 3", time(9, 40), time(10, 20), False),
    ):
        p[name] = Period.objects.create(
            school=kit.school, name=name, starts_at=start, ends_at=end, is_break=is_break
        )
    kit.periods = p
    kit.english = Subject.objects.create(school=kit.school, name="English")
    kit.english_teacher = make_user("teacher")
    assign(kit.english_teacher, kit.classroom, kit.english)
    kit.other_class = make_classroom(kit.school, "B")
    assign(kit.teacher, kit.other_class, kit.subject)
    return kit


def lesson(kit, day, period, subject):
    return {"day": day, "period": kit.periods[period].pk, "subject": subject.pk}


def put_week(auth, kit, lessons, classroom=None, user=None):
    body = {"classroom": (classroom or kit.classroom).pk, "lessons": lessons}
    return auth(user or kit.admin).put(CLASS_URL, body, format="json")


@pytest.fixture
def admin_kit(day, admin_user):
    day.admin = admin_user
    return day


# --- periods ---------------------------------------------------------------------------------


def test_periods(auth, kit, admin_user):
    client = auth(admin_user)
    r = client.post(PERIODS_URL, {"name": "Period 1", "starts_at": "08:00", "ends_at": "08:40"})
    assert r.status_code == 201, r.content
    overlap = client.post(PERIODS_URL, {"name": "P2", "starts_at": "08:30", "ends_at": "09:10"})
    assert overlap.status_code == 400 and "overlaps Period 1 (08:00-08:40)" in str(overlap.json())
    backwards = client.post(PERIODS_URL, {"name": "P2", "starts_at": "10:00", "ends_at": "09:00"})
    assert backwards.status_code == 400
    same_name = client.post(
        PERIODS_URL, {"name": "period 1", "starts_at": "11:00", "ends_at": "11:40"}
    )
    assert same_name.status_code == 400
    assert auth(kit.teacher).post(PERIODS_URL, {}).status_code == 403
    rows = auth(kit.student).get(PERIODS_URL).json()["results"]
    assert [p["name"] for p in rows] == ["Period 1"]


# --- a class's week --------------------------------------------------------------------------


def test_building_a_class_week(auth, admin_kit, spec):
    kit = admin_kit
    r = put_week(
        auth,
        kit,
        [
            lesson(kit, 1, "Period 1", kit.subject),
            lesson(kit, 1, "Period 2", kit.english),
            lesson(kit, 3, "Period 3", kit.subject),
        ],
    )
    assert r.status_code == 200, r.content
    week = r.json()
    assert [p["name"] for p in week["periods"]] == ["Period 1", "Period 2", "Break", "Period 3"]
    assert [d["name"] for d in week["days"]] == [
        "Monday", "Tuesday", "Wednesday", "Thursday", "Friday",
    ]  # fmt: skip
    monday = week["days"][0]["lessons"]
    assert monday[0]["subject"]["name"] == "Mathematics"
    assert monday[0]["teacher"]["id"] == kit.teacher.pk
    assert monday[1]["teacher"]["id"] == kit.english_teacher.pk
    assert monday[2] is None and monday[3] is None
    assert week["days"][2]["lessons"][3]["subject"]["name"] == "Mathematics"
    assert week["can_edit"] is True

    # replacing the week: what's left out comes off
    r = put_week(auth, kit, [lesson(kit, 6, "Period 1", kit.english)])
    assert r.status_code == 200
    assert Slot.objects.count() == 1
    assert r.json()["days"][-1]["name"] == "Saturday"  # shown because something is on it
    [entry] = AuditEntry.objects.filter(action="timetable.replaced").order_by("-pk")[:1]
    assert entry.changes["new"] == ["Saturday Period 1: English"]


def test_week_validation(auth, admin_kit):
    kit = admin_kit
    chemistry = Subject.objects.create(school=kit.school, name="Chemistry")
    r = put_week(
        auth,
        kit,
        [
            lesson(kit, 1, "Break", kit.subject),
            lesson(kit, 1, "Period 1", chemistry),
            lesson(kit, 2, "Period 1", kit.subject),
            lesson(kit, 2, "Period 1", kit.english),
        ],
    )
    assert r.status_code == 400
    errors = r.json()["lessons"]
    assert "Break is a break" in str(errors[0])
    assert "Nobody teaches Chemistry to JSS1A" in str(errors[1])
    assert errors[2] == {} and "given twice" in str(errors[3])
    assert Slot.objects.count() == 0  # all or nothing
    sunday = {"day": 7, "period": kit.periods["Period 2"].pk, "subject": kit.subject.pk}
    assert put_week(auth, kit, [sunday]).status_code == 400


def test_teachers_cant_be_in_two_places(auth, admin_kit):
    kit = admin_kit
    assert put_week(auth, kit, [lesson(kit, 1, "Period 1", kit.subject)]).status_code == 200
    r = put_week(auth, kit, [lesson(kit, 1, "Period 1", kit.subject)], classroom=kit.other_class)
    assert r.status_code == 400
    assert "already teaches JSS1A Mathematics on Monday, Period 1" in str(r.json())
    # the same teacher in the next period is fine
    ok = put_week(auth, kit, [lesson(kit, 1, "Period 2", kit.subject)], classroom=kit.other_class)
    assert ok.status_code == 200


def test_who_sees_a_class_week(auth, admin_kit, make_user):
    kit = admin_kit
    put_week(auth, kit, [lesson(kit, 1, "Period 1", kit.subject)])
    query = {"classroom": kit.classroom.pk}
    parent = make_user("parent")
    Guardianship.objects.create(parent=parent, student=kit.student)
    for reader in (kit.teacher, kit.other_teacher, kit.student, parent):
        r = auth(reader).get(CLASS_URL, query)
        assert r.status_code == 200, reader.role
        assert r.json()["can_edit"] is False
    for outsider in (kit.outsider, make_user("parent")):
        assert auth(outsider).get(CLASS_URL, query).status_code == 404
    assert auth(kit.student).get(CLASS_URL, {"classroom": kit.other_class.pk}).status_code == 404
    denied = put_week(auth, kit, [], user=kit.teacher)
    assert denied.status_code == 403


# --- a teacher's week ------------------------------------------------------------------------


def test_teacher_week(auth, admin_kit):
    kit = admin_kit
    put_week(auth, kit, [lesson(kit, 1, "Period 1", kit.subject)])
    put_week(auth, kit, [lesson(kit, 2, "Period 3", kit.subject)], classroom=kit.other_class)
    week = auth(kit.teacher).get(TEACHER_URL).json()
    assert week["teacher"]["id"] == kit.teacher.pk
    taught = [
        (d["name"], kit_period["name"], cell["classroom"]["name"])
        for d in week["days"]
        for kit_period, cell in zip(week["periods"], d["lessons"], strict=True)
        if cell
    ]
    assert taught == [("Monday", "Period 1", "JSS1A"), ("Tuesday", "Period 3", "JSS1B")]
    by_admin = auth(kit.admin).get(TEACHER_URL, {"teacher": kit.teacher.pk})
    assert by_admin.json() == week
    assert auth(kit.student).get(TEACHER_URL).status_code == 403
    assert auth(kit.admin).get(TEACHER_URL).status_code == 404  # say which teacher


# --- keeping it consistent -------------------------------------------------------------------


def test_teaching_assignment_changes(auth, admin_kit, make_user):
    kit = admin_kit
    put_week(auth, kit, [lesson(kit, 1, "Period 1", kit.english)])
    put_week(auth, kit, [lesson(kit, 1, "Period 1", kit.subject)], classroom=kit.other_class)
    english = kit.english_teacher.teaching_assignments.get()
    url = f"/api/v1/academics/teaching-assignments/{english.pk}/"
    client = auth(kit.admin)
    # kit.teacher is in JSS1B at that time: handing them JSS1A's English would double-book
    clash = client.patch(url, {"teacher": kit.teacher.pk}, format="json")
    assert clash.status_code == 400 and "already teaches JSS1B" in str(clash.json())
    moved = client.patch(url, {"classroom": kit.other_class.pk}, format="json")
    assert moved.status_code == 409
    substitute = make_user("teacher")
    assert client.patch(url, {"teacher": substitute.pk}, format="json").status_code == 200
    cell = client.get(CLASS_URL, {"classroom": kit.classroom.pk}).json()["days"][0]["lessons"][0]
    assert cell["teacher"]["id"] == substitute.pk  # the timetable follows the assignment

    assert client.delete(url).status_code == 204
    assert not Slot.objects.filter(classroom=kit.classroom).exists()
    period = kit.periods["Period 1"]
    assert client.delete(f"{PERIODS_URL}{period.pk}/").status_code == 409  # JSS1B uses it


def test_rollover_keeps_the_timetable(auth, admin_kit):
    kit = admin_kit
    put_week(auth, kit, [lesson(kit, 1, "Period 1", kit.subject)], classroom=kit.other_class)
    make_classroom(kit.school, "A", level_order=2)
    make_classroom(kit.school, "B", level_order=2)
    following = create_session(kit.school, "2026/2027")
    r = auth(kit.admin).post(
        "/api/v1/academics/rollover/", {"to_session": following.pk, "commit": True}, format="json"
    )
    assert r.status_code == 200, r.content
    copied = Slot.objects.get(session=following)
    assert (copied.classroom, copied.day, copied.period) == (
        kit.other_class,
        1,
        kit.periods["Period 1"],
    )
    assert copied.assignment.session == following
    assert Slot.objects.filter(session=kit.session).count() == 1  # this year's untouched


def test_todays_lessons_on_dashboards(auth, admin_kit):
    kit = admin_kit
    put_week(
        auth,
        kit,
        [lesson(kit, 1, "Period 3", kit.subject), lesson(kit, 1, "Period 1", kit.english)],
    )
    with mock.patch.object(School, "today", return_value=MONDAY):
        student = auth(kit.student).get("/api/v1/dashboard/").json()["student"]
        teacher = auth(kit.teacher).get("/api/v1/dashboard/").json()["teacher"]
    assert [(t["name"], t["subject"]["name"]) for t in student["timetable_today"]] == [
        ("Period 1", "English"),
        ("Period 3", "Mathematics"),
    ]
    assert student["timetable_today"][0]["starts_at"] == "08:00"
    assert [t["classroom"]["name"] for t in teacher["timetable_today"]] == ["JSS1A"]
