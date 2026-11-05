"""Moving a school into the next session: default promotions, decisions, graduates, errors,
teaching assignments, re-running, and cost."""

from types import SimpleNamespace

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.academics.models import Enrollment, Subject, TeachingAssignment
from apps.academics.services import create_session
from conftest import assign, check, enroll, make_classroom, response_schema

pytestmark = pytest.mark.django_db

URL = "/api/v1/academics/rollover/"


@pytest.fixture
def year(school, make_user):
    """JSS1A (Ada, Bayo), JSS1B (Chi), JSS2A, SS3A (Dayo, final level); maths taught in JSS1A;
    next session 2026/2027 created."""
    jss1a, jss1b = make_classroom(school, "A", 1), make_classroom(school, "B", 1)
    jss2a = make_classroom(school, "A", 2)
    ss3a = make_classroom(school, "A", 6)
    people = {}
    for name, room in (("ada", jss1a), ("bayo", jss1a), ("chi", jss1b), ("dayo", ss3a)):
        people[name] = make_user("student", username=name)
        enroll(people[name], room)
    teacher = make_user("teacher")
    maths = Subject.objects.create(school=school, name="Mathematics")
    assign(teacher, jss1a, maths)
    return SimpleNamespace(
        school=school,
        jss1a=jss1a,
        jss1b=jss1b,
        jss2a=jss2a,
        ss3a=ss3a,
        teacher=teacher,
        current=school.academic_sessions.get(is_current=True),
        next=create_session(school, "2026/2027"),
        **people,
    )


def run(client, year, commit=False, **extra):
    body = {"to_session": year.next.pk, "commit": commit, **extra}
    return client.post(URL, body, format="json")


def rows(response):
    return {r["student"]["name"]: r for r in response.json()["students"]}


def test_preview_promotes_and_graduates_by_default(auth, admin_user, year, spec):
    r = run(auth(admin_user), year)
    assert r.status_code == 200, r.content
    check(spec, response_schema(spec, "academics/rollover/", "post", 200), r.json(), "rollover")
    plan = rows(r)
    assert plan["ada"]["to_classroom"]["name"] == "JSS2A"
    assert plan["chi"]["to_classroom"]["name"] == "JSS2A"  # JSS2 has a single class
    assert plan["dayo"]["action"] == "graduate" and plan["dayo"]["to_classroom"] is None
    data = r.json()
    assert data["valid"] and not data["committed"]
    assert data["summary"]["promoted"] == 3 and data["summary"]["graduating"] == 1
    assert data["summary"]["teaching_assignments_copied"] == 1
    assert [t["name"] for t in data["unpublished_terms"]] == [
        "First Term",
        "Second Term",
        "Third Term",
    ]
    assert not Enrollment.objects.filter(session=year.next).exists()


def test_commit_with_decisions(auth, admin_user, year):
    decisions = [
        {"student": year.bayo.pk, "action": "repeat"},
        {"student": year.chi.pk, "action": "leave"},
    ]
    r = run(auth(admin_user), year, commit=True, decisions=decisions, make_current=True)
    assert r.status_code == 200 and r.json()["committed"], r.content
    placed = dict(
        Enrollment.objects.filter(session=year.next).values_list(
            "student__username", "classroom__arm"
        )
    )
    assert set(placed) == {"ada", "bayo"}  # chi left, dayo graduated
    ada_class = Enrollment.objects.get(session=year.next, student=year.ada).classroom
    bayo_class = Enrollment.objects.get(session=year.next, student=year.bayo).classroom
    assert ada_class == year.jss2a and bayo_class == year.jss1a
    assert TeachingAssignment.objects.filter(
        session=year.next, classroom=year.jss1a, teacher=year.teacher
    ).exists()
    year.next.refresh_from_db()
    assert year.next.is_current
    assert year.next.terms.get(is_current=True).order == 1
    # last year's enrollments are untouched: report cards still find their class
    assert Enrollment.objects.filter(session=year.current).count() == 4


def test_running_again_changes_nothing(auth, admin_user, year):
    client = auth(admin_user)
    run(client, year, commit=True)
    again = run(client, year, commit=True)
    assert again.status_code == 200
    summary = again.json()["summary"]
    assert summary["already_done"] == 4 and summary["promoted"] == 0  # dayo graduated
    assert summary["teaching_assignments_copied"] == 0
    assert Enrollment.objects.filter(session=year.next).count() == 3
    assert TeachingAssignment.objects.filter(session=year.next).count() == 1


def test_students_who_cant_be_placed_block_the_commit(auth, admin_user, year, school):
    make_classroom(school, "C", 2)  # JSS2 now has A and C: JSS1B has no obvious next class
    client = auth(admin_user)
    plan = rows(run(client, year))
    assert "no arm B" in plan["chi"]["error"]
    r = run(client, year, commit=True)
    assert r.status_code == 400 and r.json()["committed"] is False
    assert not Enrollment.objects.filter(session=year.next).exists()

    move = [{"student": year.chi.pk, "action": "move", "classroom": year.jss2a.pk}]
    assert run(client, year, commit=True, decisions=move).status_code == 200
    assert Enrollment.objects.get(session=year.next, student=year.chi).classroom == year.jss2a


def test_decision_errors(auth, admin_user, year, make_user, other_school):
    client = auth(admin_user)
    no_class = run(client, year, decisions=[{"student": year.ada.pk, "action": "move"}])
    assert "class" in rows(no_class)["ada"]["error"]

    outsider = make_user("student")  # in the school, not in a class
    r = run(client, year, decisions=[{"student": outsider.pk, "action": "repeat"}])
    assert r.status_code == 400 and "decisions" in r.json()

    their_class = make_classroom(other_school, "A")
    bad = [{"student": year.ada.pk, "action": "move", "classroom": their_class.pk}]
    assert run(client, year, decisions=bad).status_code == 400

    same = client.post(URL, {"to_session": year.current.pk}, format="json")
    assert same.status_code == 400 and "to_session" in same.json()


def test_final_level_can_repeat_and_latest_average_shows(auth, admin_user, year, term):
    from apps.results.models import Score

    english = Subject.objects.create(school=year.school, name="English")
    component = year.school.components.first()
    Score.objects.create(
        student=year.dayo, subject=english, term=term, component=component, value=18
    )
    client = auth(admin_user)
    assert client.post("/api/v1/results/publish/", {}).status_code == 201
    r = run(client, year, decisions=[{"student": year.dayo.pk, "action": "repeat"}])
    dayo = rows(r)["dayo"]
    assert dayo["to_classroom"]["name"] == "SS3A" and dayo["latest_average"] == "18.00"
    assert [t["name"] for t in r.json()["unpublished_terms"]] == ["Second Term", "Third Term"]


def test_only_admins(auth, year):
    assert run(auth(year.teacher), year).status_code == 403


def test_cost_does_not_grow_with_students(auth, admin_user, year, make_user):
    client = auth(admin_user)
    with CaptureQueriesContext(connection) as small:
        run(client, year)
    for _ in range(15):
        enroll(make_user("student"), year.jss1a)
    with CaptureQueriesContext(connection) as big:
        run(client, year)
    assert len(big) == len(small)


def test_outcomes_are_recorded_and_respected(auth, admin_user, year):
    client = auth(admin_user)
    decisions = [{"student": year.chi.pk, "action": "leave"}]
    run(client, year, commit=True, decisions=decisions)
    outcomes = dict(
        Enrollment.objects.filter(session=year.current).values_list("student__username", "outcome")
    )
    assert outcomes == {"ada": "promoted", "bayo": "promoted", "chi": "left", "dayo": "graduated"}
    # a later run doesn't bring back the leaver or the graduate...
    again = run(client, year, commit=True)
    assert again.json()["summary"]["already_done"] == 4
    assert not Enrollment.objects.filter(session=year.next, student=year.chi).exists()
    # ...unless the admin says so: chi came back
    back = [{"student": year.chi.pk, "action": "move", "classroom": year.jss2a.pk}]
    r = run(client, year, commit=True, decisions=back)
    assert r.status_code == 200 and r.json()["summary"]["moved"] == 1
    assert Enrollment.objects.get(session=year.current, student=year.chi).outcome == "moved"
    enrollment = Enrollment.objects.get(session=year.current, student=year.dayo)
    api_row = client.get(f"/api/v1/academics/enrollments/{enrollment.pk}/").json()
    assert api_row["outcome"] == "graduated"
