"""Each session has its own score split: copied forward, editable for next year while this
year's is locked, and always the one a term's scores are entered and computed against."""

import importlib

import pytest

from apps.academics.services import create_session, make_term_current
from apps.results.models import Score
from apps.schools.models import AssessmentComponent, School

pytestmark = pytest.mark.django_db

URL = "/api/v1/schools/components/"
SHEET_URL = "/api/v1/results/score-sheet/"
NEW_SPLIT = {"components": [{"name": "CA", "max_score": 40}, {"name": "Exam", "max_score": 60}]}


def names(queryset):
    return [(c.name, c.max_score) for c in queryset]


def enter_exam(auth, kit, value=50, term=None):
    split = {c.name: c for c in kit.school.score_split((term or kit.term).session)}
    body = {
        "classroom": kit.classroom.pk,
        "subject": kit.subject.pk,
        "scores": [{"student": kit.student.pk, "component": split["Exam"].pk, "value": value}],
    }
    if term is not None:
        body["term"] = term.pk
    return auth(kit.teacher).put(SHEET_URL, body, format="json")


def test_a_new_session_copies_the_latest_split(kit, auth, admin_user):
    assert auth(admin_user).put(URL, NEW_SPLIT, format="json").status_code == 200
    following = create_session(kit.school, "2026/2027")
    assert names(kit.school.score_split(following)) == [("CA", 40), ("Exam", 60)]
    # copies, not shared rows
    assert not set(kit.school.score_split(following)) & set(kit.school.score_split(kit.session))


def test_next_years_split_changes_while_this_years_is_locked(kit, auth, admin_user):
    assert enter_exam(auth, kit).status_code == 200
    client = auth(admin_user)
    locked = client.put(URL, NEW_SPLIT, format="json")
    assert locked.status_code == 409 and "next session" in locked.json()["detail"]

    following = create_session(kit.school, "2026/2027")
    r = client.put(f"{URL}?session={following.pk}", NEW_SPLIT, format="json")
    assert r.status_code == 200, r.content
    assert r.json()["session"] == {"id": following.pk, "name": "2026/2027"}
    assert names(kit.school.score_split(kit.session)) == [("CA1", 20), ("CA2", 20), ("Exam", 60)]

    current = client.get(URL).json()
    assert current["session"]["id"] == kit.session.pk and len(current["components"]) == 3


def test_scores_use_their_own_sessions_split(kit, auth, admin_user):
    enter_exam(auth, kit, 50)
    following = create_session(kit.school, "2026/2027")
    auth(admin_user).put(f"{URL}?session={following.pk}", NEW_SPLIT, format="json")
    next_term = following.terms.get(order=1)
    from conftest import assign, enroll

    enroll(kit.student, kit.classroom, session=following)
    assign(kit.teacher, kit.classroom, kit.subject, session=following)

    # last year's sheet keeps CA1/CA2/Exam; next year's shows CA/Exam
    old = auth(kit.teacher).get(
        SHEET_URL, {"classroom": kit.classroom.pk, "subject": kit.subject.pk}
    )
    assert [c["name"] for c in old.json()["components"]] == ["CA1", "CA2", "Exam"]
    assert enter_exam(auth, kit, 55, term=next_term).status_code == 200
    new = auth(kit.teacher).get(
        SHEET_URL,
        {"classroom": kit.classroom.pk, "subject": kit.subject.pk, "term": next_term.pk},
    )
    assert [c["name"] for c in new.json()["components"]] == ["CA", "Exam"]

    # a component from the other session's split is refused
    wrong = kit.school.score_split(kit.session).get(name="Exam")
    body = {
        "classroom": kit.classroom.pk,
        "subject": kit.subject.pk,
        "term": next_term.pk,
        "scores": [{"student": kit.student.pk, "component": wrong.pk, "value": 10}],
    }
    r = auth(kit.teacher).put(SHEET_URL, body, format="json")
    assert r.status_code == 400 and "unknown component" in str(r.json())

    # publishing next year's term prints next year's split on the card
    make_term_current(next_term)
    assert auth(admin_user).post("/api/v1/results/publish/", {}).status_code == 202
    card = auth(kit.student).get("/api/v1/results/report-card/").json()
    assert [s["component"] for s in card["subjects"][0]["scores"]] == ["CA", "Exam"]


def test_school_without_a_session_edits_its_default(api, auth):
    from django.contrib.auth import get_user_model

    from apps.schools.services import onboard_school

    school, admin = onboard_school(
        name="Fresh School",
        system=School.System.NG,
        admin={"username": "fresh", "email": "f@x.org", "password": "Fresh-Pass-2026!"},
    )
    assert get_user_model().objects.filter(pk=admin.pk).exists()
    r = auth(admin).put(URL, NEW_SPLIT, format="json")
    assert r.status_code == 200 and r.json()["session"] is None
    first = create_session(school, "2025/2026")
    assert names(school.score_split(first)) == [("CA", 40), ("Exam", 60)]


def test_session_parameter_is_checked(kit, auth, admin_user, other_school):
    client = auth(admin_user)
    theirs = other_school.academic_sessions.first()
    assert client.get(URL, {"session": theirs.pk}).status_code == 404
    assert client.get(URL, {"session": "abc"}).status_code == 400


def test_migration_gives_each_session_its_own_split(kit):
    """The data migration on real models: scores move onto their session's copy."""
    from django.apps import apps

    migration = importlib.import_module("apps.schools.migrations.0003_copy_split_into_sessions")
    school = kit.school
    # rebuild the old world: one school-wide split that every session's scores use
    AssessmentComponent.objects.filter(school=school, session__isnull=False).delete()
    default = school.score_split(None).get(name="Exam")
    following = create_session(school, "2026/2027")
    AssessmentComponent.objects.filter(school=school, session__isnull=False).delete()
    this_year = Score.objects.create(
        student=kit.student, subject=kit.subject, term=kit.term, component=default, value=50
    )
    next_year = Score.objects.create(
        student=kit.student,
        subject=kit.subject,
        term=following.terms.first(),
        component=default,
        value=60,
    )

    migration.split_by_session(apps, None)
    this_year.refresh_from_db()
    next_year.refresh_from_db()
    assert this_year.component.session == kit.session and this_year.component.name == "Exam"
    assert next_year.component.session == following
    assert names(school.score_split(kit.session)) == [("CA1", 20), ("CA2", 20), ("Exam", 60)]
    assert not Score.objects.filter(component__session__isnull=True).exists()

    migration.merge_back(apps, None)  # and it can be undone
    this_year.refresh_from_db()
    assert this_year.component.session is None and this_year.component.name == "Exam"
