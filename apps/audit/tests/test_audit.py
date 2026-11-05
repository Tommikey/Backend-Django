"""The audit log: who changed marks, attendance, comments, people, classes and settings, and
who published results. Admins read it; nobody edits it."""

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.academics.services import create_session
from apps.accounts.models import Guardianship
from apps.assessments.models import Assessment, Submission
from apps.audit.models import AuditEntry
from apps.results.tests.test_api import components, enter
from conftest import PASSWORD, enroll, make_classroom, results

pytestmark = pytest.mark.django_db

URL = "/api/v1/audit/"


def log(auth, admin, **params):
    r = auth(admin).get(URL, params)
    assert r.status_code == 200, r.content
    return results(r.json())


def actions(entries):
    return [e["action"] for e in entries]


# --- marks, attendance, comments, results ----------------------------------------------------


def test_score_changes(auth, kit, admin_user, spec):
    enter(auth, kit, CA1=12, CA2=15)
    enter(auth, kit, CA1=14, CA2=15)  # CA2 unchanged
    enter(auth, kit, CA1=14)  # nothing changed: no entry
    enter(auth, kit, CA1=None)  # cleared

    entries = log(auth, admin_user, action="scores")
    assert len(entries) == 3
    cleared, changed, first = entries  # newest first
    name = kit.student.display_name
    assert first["changes"] == [
        {"student": kit.student.pk, "student_name": name, "component": "CA1", "old": None,
         "new": "12.00"},
        {"student": kit.student.pk, "student_name": name, "component": "CA2", "old": None,
         "new": "15.00"},
    ]  # fmt: skip
    assert [(c["component"], c["old"], c["new"]) for c in changed["changes"]] == [
        ("CA1", "12.00", "14.00")
    ]
    assert [(c["old"], c["new"]) for c in cleared["changes"]] == [("14.00", None)]
    assert first["actor"] == kit.teacher.pk and kit.teacher.username in first["actor_name"]
    assert first["context"]["classroom"] == {"id": kit.classroom.pk, "name": "JSS1A"}
    assert first["context"]["subject"]["name"] == "Mathematics"
    assert first["ip"] == "127.0.0.1"

    # one student's history; one class's
    assert len(log(auth, admin_user, student=kit.student.pk)) == 3
    assert log(auth, admin_user, student=kit.outsider.pk) == []
    assert len(log(auth, admin_user, classroom=kit.classroom.pk, action="scores.updated")) == 3
    assert len(log(auth, admin_user, term=kit.term.pk)) == 3


def test_register_and_comments(auth, kit, admin_user):
    kit.classroom.form_teacher = kit.teacher
    kit.classroom.save()
    body = {
        "classroom": kit.classroom.pk,
        "date": kit.school.today().isoformat(),
        "marks": [{"student": kit.student.pk, "status": "present"}],
    }
    client = auth(kit.teacher)
    client.put("/api/v1/attendance/register/", body, format="json")
    body["marks"][0]["status"] = "late"
    client.put("/api/v1/attendance/register/", body, format="json")
    client.put("/api/v1/attendance/register/", body, format="json")  # same again: no entry
    entries = log(auth, admin_user, action="attendance")
    assert [[(c["old"], c["new"]) for c in e["changes"]] for e in entries] == [
        [("present", "late")],
        [(None, "present")],
    ]
    assert entries[0]["context"]["date"] == kit.school.today().isoformat()

    comment = {"student": kit.student.pk, "form_teacher_comment": "Works hard."}
    client.put("/api/v1/results/comments/", comment, format="json")
    [entry] = log(auth, admin_user, action="comments.updated")
    assert entry["changes"] == {"form_teacher_comment": ["", "Works hard."]}
    assert entry["target_type"] == "user" and entry["target_id"] == kit.student.pk


def test_publishing_and_unpublishing(auth, kit, admin_user):
    client = auth(admin_user)
    client.post("/api/v1/results/publish/", {})
    client.post("/api/v1/results/unpublish/", {})
    entries = log(auth, admin_user, action="results")
    assert actions(entries) == ["results.unpublished", "results.published"]
    assert all(e["actor"] == admin_user.pk and e["target_id"] == kit.term.pk for e in entries)
    assert entries[1]["changes"] == {"report_cards": 1}


def test_grading(auth, kit, admin_user):
    essay = Assessment.objects.create(
        title="Essay", type="assignment", classroom=kit.classroom, subject=kit.subject,
        term=kit.term,
    )  # fmt: skip
    sub = Submission.objects.create(assessment=essay, student=kit.student, text="...")
    auth(kit.teacher).patch(f"/api/v1/submissions/{sub.pk}/", {"score": 70}, format="json")
    auth(kit.teacher).patch(f"/api/v1/submissions/{sub.pk}/", {"score": 75}, format="json")
    entries = log(auth, admin_user, action="submission")
    assert [e["changes"] for e in entries] == [{"score": [70.0, 75.0]}, {"score": [None, 70.0]}]
    assert entries[0]["context"]["student"]["id"] == kit.student.pk
    assert len(log(auth, admin_user, student=kit.student.pk)) == 2


# --- people and classes ----------------------------------------------------------------------


def test_people_changes(auth, kit, admin_user):
    client = auth(admin_user)
    r = client.post(
        "/api/v1/users/",
        {"username": "newt", "role": "teacher", "password": PASSWORD, "first_name": "Newt"},
        format="json",
    )
    assert r.status_code == 201, r.content
    user_id = r.json()["id"]
    client.patch(f"/api/v1/users/{user_id}/", {"is_active": False}, format="json")
    client.patch(f"/api/v1/users/{user_id}/", {"password": "Another-Pass-77"}, format="json")
    client.post(f"/api/v1/users/{user_id}/activation-code/")
    client.delete(f"/api/v1/users/{user_id}/")

    entries = log(auth, admin_user, target_type="user", target_id=user_id)
    assert actions(entries) == [
        "user.deleted",
        "user.activation_code_issued",
        "user.updated",
        "user.updated",
        "user.created",
    ]
    deleted, _, password, deactivated, created = entries
    assert created["changes"]["username"] == [None, "newt"]
    assert "password" not in created["changes"]
    assert deactivated["changes"] == {"is_active": [True, False]}
    assert password["changes"] == {"password": [None, "reset"]}  # never the password itself
    assert "Another-Pass" not in str(AuditEntry.objects.values_list("changes", flat=True))
    assert deleted["target_label"] == "Newt (newt)"


def test_own_password_change(auth, kit, admin_user):
    r = auth(kit.teacher).post(
        "/api/v1/auth/password/",
        {"current_password": PASSWORD, "new_password": "Brand-New-Pass-88"},
        format="json",
    )
    assert r.status_code == 200, r.content
    [entry] = log(auth, admin_user, action="user.password_changed")
    assert entry["actor"] == entry["target_id"] == kit.teacher.pk


def test_class_membership_and_teaching(auth, kit, admin_user, make_user):
    client = auth(admin_user)
    parent = make_user("parent")
    link = client.post(
        "/api/v1/guardianships/",
        {"parent": parent.pk, "student": kit.student.pk},
        format="json",
    )
    assert link.status_code == 201, link.content
    client.delete(f"/api/v1/guardianships/{link.json()['id']}/")
    other = make_classroom(kit.school, "B")
    enrollment = kit.student.enrollments.get()
    client.patch(
        f"/api/v1/academics/enrollments/{enrollment.pk}/", {"classroom": other.pk}, format="json"
    )
    client.patch(
        f"/api/v1/academics/classrooms/{kit.classroom.pk}/",
        {"form_teacher": kit.teacher.pk},
        format="json",
    )
    assignment = kit.teacher.teaching_assignments.get()
    client.delete(f"/api/v1/academics/teaching-assignments/{assignment.pk}/")

    about_student = log(auth, admin_user, student=kit.student.pk)
    assert actions(about_student) == [
        "enrollment.updated",
        "guardianship.deleted",
        "guardianship.created",
    ]
    assert about_student[0]["changes"] == {"classroom": [kit.classroom.pk, other.pk]}
    assert "is a parent of" in about_student[1]["target_label"]
    [form] = log(auth, admin_user, action="classroom.updated")
    assert form["changes"] == {"form_teacher": [None, kit.teacher.pk]}
    [removed] = log(auth, admin_user, action="teachingassignment.deleted")
    assert "Mathematics, JSS1A" in removed["target_label"]
    assert removed["target_id"] == assignment.pk


def test_import_and_rollover(auth, kit, admin_user):
    client = auth(admin_user)
    csv = "role,first_name,last_name,classroom\nstudent,Ngozi,Eze,JSS1A\nteacher,Tunde,Bello,\n"
    r = client.post(
        "/api/v1/imports/people/",
        {"file": SimpleUploadedFile("term1.csv", csv.encode()), "commit": "true"},
        format="multipart",
    )
    assert r.status_code == 200, r.content
    [imported] = log(auth, admin_user, action="people.imported")
    assert imported["changes"] == {"created": {"student": 1, "teacher": 1}}
    assert imported["target_label"] == "2 people from term1.csv"

    make_classroom(kit.school, "A", level_order=2)  # JSS2A, to promote into
    following = create_session(kit.school, "2026/2027")
    r = client.post(
        "/api/v1/academics/rollover/", {"to_session": following.pk, "commit": True}, format="json"
    )
    assert r.status_code == 200, r.content
    [rolled] = log(auth, admin_user, action="rollover.applied")
    assert rolled["changes"]["promoted"] == 2 and rolled["target_label"] == "2025/2026 to 2026/2027"


# --- settings --------------------------------------------------------------------------------


def test_settings_changes(auth, kit, admin_user):
    client = auth(admin_user)
    old_split = list(components(kit))
    shown = kit.school.show_position
    client.patch("/api/v1/schools/me/", {"show_position": not shown}, format="json")
    split = [{"name": n, "max_score": m} for n, m in (("Test", 30), ("Project", 10), ("Exam", 60))]
    r = client.put("/api/v1/schools/components/", {"components": split}, format="json")
    assert r.status_code == 200, r.content
    entries = log(auth, admin_user)
    assert actions(entries) == ["components.replaced", "school.updated"]
    assert entries[1]["changes"] == {"show_position": [shown, not shown]}
    replaced = entries[0]
    assert replaced["target_label"] == "Score split, 2025/2026"
    assert [c["name"] for c in replaced["changes"]["old"]] == old_split == ["CA1", "CA2", "Exam"]
    assert [c["name"] for c in replaced["changes"]["new"]] == ["Test", "Project", "Exam"]


# --- who reads it ----------------------------------------------------------------------------


def test_only_admins_read_their_schools_log(auth, kit, admin_user, make_user, other_school):
    enter(auth, kit, CA1=10)
    assert len(log(auth, admin_user)) == 1
    assert auth(kit.teacher).get(URL).status_code == 403
    assert auth(make_user("admin", school=other_school)).get(URL).json()["results"] == []
    entry_id = AuditEntry.objects.get().pk
    client = auth(admin_user)
    assert client.delete(f"{URL}{entry_id}/").status_code == 405
    assert client.patch(f"{URL}{entry_id}/", {"action": "x"}).status_code == 405
    assert client.post(URL, {}).status_code == 405


def test_filters_check_their_input(auth, admin_user):
    client = auth(admin_user)
    assert client.get(URL, {"since": "yesterday"}).status_code == 400
    assert client.get(URL, {"student": "ada"}).status_code == 400
    assert client.get(URL, {"since": "2020-01-01", "until": "2099-12-31"}).status_code == 200


def test_ip_behind_a_proxy(auth, kit, admin_user, settings):
    settings.REST_FRAMEWORK = {**settings.REST_FRAMEWORK, "NUM_PROXIES": 1}
    client = auth(kit.teacher)
    body = {
        "classroom": kit.classroom.pk,
        "subject": kit.subject.pk,
        "scores": [{"student": kit.student.pk, "component": components(kit)["CA1"].pk, "value": 9}],
    }
    client.put(
        "/api/v1/results/score-sheet/",
        body,
        format="json",
        HTTP_X_FORWARDED_FOR="203.0.113.7, 10.0.0.2",
    )
    assert AuditEntry.objects.get().ip == "10.0.0.2"  # the address our one proxy saw


def test_parents_and_students_cant_read_it(auth, kit, make_user):
    parent = make_user("parent")
    Guardianship.objects.create(parent=parent, student=kit.student)
    enroll(make_user("student"), kit.classroom)
    for user in (parent, kit.student):
        assert auth(user).get(URL).status_code == 403
