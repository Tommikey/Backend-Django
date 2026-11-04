"""Setting up the school year: sessions and terms, classes, who teaches what, who is where."""

import pytest

from apps.academics.models import AcademicSession, Enrollment, Lesson, Subject, Term
from conftest import assign, enroll, make_classroom, results

pytestmark = pytest.mark.django_db

SESSIONS_URL = "/api/v1/academics/academic-sessions/"
TERMS_URL = "/api/v1/academics/terms/"
CLASSES_URL = "/api/v1/academics/classrooms/"
ASSIGN_URL = "/api/v1/academics/teaching-assignments/"
ENROLL_URL = "/api/v1/academics/enrollments/"


# --- sessions and terms ------------------------------------------------------------------------


def test_new_session_gets_the_schools_terms(auth, admin_user, school):
    r = auth(admin_user).post(
        SESSIONS_URL, {"name": "2026/2027", "starts_on": "2026-09-08", "ends_on": "2027-07-20"}
    )
    assert r.status_code == 201, r.content
    assert [t["name"] for t in r.json()["terms"]] == ["First Term", "Second Term", "Third Term"]
    assert r.json()["is_current"] is False  # creating a session doesn't switch to it


def test_terms_follow_the_schools_own_names(auth, admin_user, school):
    school.term_labels = ["Fall Semester", "Spring Semester"]
    school.save()
    r = auth(admin_user).post(SESSIONS_URL, {"name": "2026/2027"})
    assert [t["name"] for t in r.json()["terms"]] == ["Fall Semester", "Spring Semester"]


def test_session_validation(auth, admin_user):
    client = auth(admin_user)
    assert client.post(SESSIONS_URL, {"name": "2025/2026"}).status_code == 400  # exists
    bad_dates = {"name": "2030/2031", "starts_on": "2031-01-01", "ends_on": "2030-01-01"}
    assert client.post(SESSIONS_URL, bad_dates).status_code == 400


def test_only_admins_set_up_the_year(auth, kit):
    for user in (kit.teacher, kit.student):
        assert auth(user).post(SESSIONS_URL, {"name": "2027/2028"}).status_code == 403
    # but everyone can see the calendar
    assert results(auth(kit.student).get(SESSIONS_URL).json())


def test_make_term_current_moves_the_school_forward(auth, admin_user, school, term):
    new = AcademicSession.objects.get(
        pk=auth(admin_user).post(SESSIONS_URL, {"name": "2026/2027"}).json()["id"]
    )
    first = new.terms.get(order=1)
    r = auth(admin_user).post(f"{TERMS_URL}{first.pk}/make-current/")
    assert r.status_code == 200, r.content
    assert r.json()["is_current"] is True
    new.refresh_from_db()
    term.refresh_from_db()
    assert new.is_current and not term.is_current
    assert not AcademicSession.objects.get(pk=term.session_id).is_current  # old year closed
    assert Term.objects.filter(session__school=school, is_current=True).count() == 1


def test_current_term_filter_and_rename(auth, admin_user, term):
    rows = results(auth(admin_user).get(f"{TERMS_URL}?current=true").json())
    assert [t["id"] for t in rows] == [term.pk]
    r = auth(admin_user).patch(f"{TERMS_URL}{term.pk}/", {"name": "1st Term"})
    assert r.status_code == 200 and r.json()["name"] == "1st Term"


def test_session_with_content_cannot_be_deleted(auth, admin_user, kit):
    Lesson.objects.create(
        title="L", classroom=kit.classroom, subject=kit.subject, term=kit.term
    )
    r = auth(admin_user).delete(f"{SESSIONS_URL}{kit.session.pk}/")
    assert r.status_code == 409
    assert AcademicSession.objects.filter(pk=kit.session.pk).exists()


# --- classes ------------------------------------------------------------------------------------


def test_admin_creates_class_arms(auth, admin_user, school, make_user):
    jss2 = school.levels.get(name="JSS2")
    form_teacher = make_user("teacher")
    r = auth(admin_user).post(
        CLASSES_URL, {"level": jss2.pk, "arm": "B", "form_teacher": form_teacher.pk}
    )
    assert r.status_code == 201, r.content
    assert r.json()["name"] == "JSS2B"
    assert r.json()["form_teacher_name"] == form_teacher.display_name
    duplicate = auth(admin_user).post(CLASSES_URL, {"level": jss2.pk, "arm": "B"})
    assert duplicate.status_code == 400
    assert "already exists" in str(duplicate.json())
    single = auth(admin_user).post(CLASSES_URL, {"level": school.levels.get(name="SS3").pk})
    assert single.status_code == 201 and single.json()["name"] == "SS3"


def test_class_rules(auth, admin_user, school, kit):
    jss1 = school.levels.get(name="JSS1")
    r = auth(admin_user).post(
        CLASSES_URL, {"level": jss1.pk, "arm": "C", "form_teacher": kit.student.pk}
    )
    assert r.status_code == 400 and "form_teacher" in r.json()
    assert auth(kit.teacher).post(CLASSES_URL, {"level": jss1.pk, "arm": "D"}).status_code == 403


def test_students_see_only_their_classes(auth, kit, school):
    make_classroom(school, "B")
    rows = results(auth(kit.student).get(CLASSES_URL).json())
    assert [c["name"] for c in rows] == ["JSS1A"]
    assert len(results(auth(kit.teacher).get(CLASSES_URL).json())) == 2


# --- who teaches what ------------------------------------------------------------------------------


def test_admin_assigns_teacher_defaulting_to_current_session(auth, admin_user, kit):
    english = Subject.objects.create(school=kit.school, name="English")
    r = auth(admin_user).post(
        ASSIGN_URL,
        {"classroom": kit.classroom.pk, "subject": english.pk, "teacher": kit.other_teacher.pk},
    )
    assert r.status_code == 201, r.content
    assert r.json()["session"] == kit.session.pk
    assert r.json()["teacher_name"] == kit.other_teacher.display_name


def test_one_teacher_per_subject_per_class(auth, admin_user, kit):
    r = auth(admin_user).post(
        ASSIGN_URL,
        {"classroom": kit.classroom.pk, "subject": kit.subject.pk, "teacher": kit.other_teacher.pk},
    )
    assert r.status_code == 400
    assert "already teaches" in str(r.json())


def test_only_teachers_can_be_assigned_and_only_by_admins(auth, admin_user, kit):
    english = Subject.objects.create(school=kit.school, name="English")
    body = {"classroom": kit.classroom.pk, "subject": english.pk, "teacher": kit.student.pk}
    assert auth(admin_user).post(ASSIGN_URL, body).status_code == 400
    body["teacher"] = kit.teacher.pk
    assert auth(kit.teacher).post(ASSIGN_URL, body).status_code == 403


def test_teacher_lists_own_assignments(auth, kit):
    english = Subject.objects.create(school=kit.school, name="English")
    assign(kit.other_teacher, kit.classroom, english)
    mine = results(auth(kit.teacher).get(f"{ASSIGN_URL}?mine=true").json())
    assert [(a["classroom_name"], a["subject_name"]) for a in mine] == [("JSS1A", "Mathematics")]
    assert len(results(auth(kit.teacher).get(ASSIGN_URL).json())) == 2


# --- who is in which class -------------------------------------------------------------------------


def test_admin_enrolls_into_current_session(auth, admin_user, kit, make_user):
    newcomer = make_user("student")
    r = auth(admin_user).post(ENROLL_URL, {"classroom": kit.classroom.pk, "student": newcomer.pk})
    assert r.status_code == 201, r.content
    assert r.json()["session"] == kit.session.pk


def test_one_class_per_student_per_session(auth, admin_user, kit):
    other_class = make_classroom(kit.school, "B")
    r = auth(admin_user).post(ENROLL_URL, {"classroom": other_class.pk, "student": kit.student.pk})
    assert r.status_code == 400
    assert "already in a class this session" in str(r.json())
    # next session they can move up
    next_session = AcademicSession.objects.create(school=kit.school, name="2026/2027")
    jss2a = make_classroom(kit.school, "A", level_order=2)
    r = auth(admin_user).post(
        ENROLL_URL,
        {"classroom": jss2a.pk, "student": kit.student.pk, "session": next_session.pk},
    )
    assert r.status_code == 201, r.content
    assert Enrollment.objects.filter(student=kit.student).count() == 2


def test_enrollment_rules(auth, admin_user, kit):
    body = {"classroom": kit.classroom.pk, "student": kit.other_teacher.pk}
    assert auth(admin_user).post(ENROLL_URL, body).status_code == 400  # not a student
    body["student"] = kit.outsider.pk
    assert auth(kit.teacher).post(ENROLL_URL, body).status_code == 403  # admins only


def test_students_see_only_own_enrollments(auth, kit):
    enroll(kit.outsider, make_classroom(kit.school, "B"))
    rows = results(auth(kit.student).get(ENROLL_URL).json())
    assert [e["student"] for e in rows] == [kit.student.pk]


def test_without_a_current_session_a_session_must_be_given(auth, admin_user, kit, make_user):
    AcademicSession.objects.update(is_current=False)
    r = auth(admin_user).post(
        ENROLL_URL, {"classroom": kit.classroom.pk, "student": make_user("student").pk}
    )
    assert r.status_code == 400
    assert "no current session" in str(r.json())


def test_subject_in_use_cannot_be_deleted(auth, admin_user, kit):
    Lesson.objects.create(title="L", classroom=kit.classroom, subject=kit.subject, term=kit.term)
    assert auth(admin_user).delete(f"/api/v1/academics/subjects/{kit.subject.pk}/").status_code == 409
