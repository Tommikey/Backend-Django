"""The results endpoints: who enters scores, publishing and locking, who reads report cards."""

import pytest

from apps.accounts.models import Guardianship
from apps.results.models import Score, TermResult

pytestmark = pytest.mark.django_db

SHEET_URL = "/api/v1/results/score-sheet/"
COMMENTS_URL = "/api/v1/results/comments/"
PUBLISH_URL = "/api/v1/results/publish/"
UNPUBLISH_URL = "/api/v1/results/unpublish/"
CARD_URL = "/api/v1/results/report-card/"
CLASS_URL = "/api/v1/results/class-results/"
COMPONENTS_URL = "/api/v1/schools/components/"


def components(kit):
    return {c.name: c for c in kit.school.score_split(kit.session)}


def sheet_body(kit, student=None, **marks):
    comps = components(kit)
    student = student or kit.student
    return {
        "classroom": kit.classroom.pk,
        "subject": kit.subject.pk,
        "scores": [
            {"student": student.pk, "component": comps[name].pk, "value": value}
            for name, value in marks.items()
        ],
    }


def sheet_query(kit):
    return {"classroom": kit.classroom.pk, "subject": kit.subject.pk}


def enter(auth, kit, user=None, **marks):
    return auth(user or kit.teacher).put(SHEET_URL, sheet_body(kit, **marks), format="json")


def make_form_teacher(kit, user):
    kit.classroom.form_teacher = user
    kit.classroom.save()


# --- score sheet -------------------------------------------------------------------------------


def test_subject_teacher_enters_and_clears_scores(auth, kit):
    r = enter(auth, kit, CA1=15, CA2="12.5", Exam=50)
    assert r.status_code == 200, r.content
    row = r.json()["rows"][0]
    assert row["total"] == "77.50"
    assert r.json()["can_edit"] is True

    r = enter(auth, kit, CA2=None)  # null clears
    assert r.json()["rows"][0]["total"] == "65.00"
    assert Score.objects.filter(student=kit.student).count() == 2

    r = auth(kit.teacher).get(SHEET_URL, sheet_query(kit))
    assert r.status_code == 200
    assert [c["name"] for c in r.json()["components"]] == ["CA1", "CA2", "Exam"]


def test_score_sheet_validation(auth, kit):
    comps = components(kit)
    over = enter(auth, kit, CA1=21)  # CA1 is out of 20
    assert over.status_code == 400 and "out of 20" in str(over.json())

    not_in_class = auth(kit.teacher).put(
        SHEET_URL, sheet_body(kit, student=kit.outsider, Exam=50), format="json"
    )
    assert not_in_class.status_code == 400

    twice = sheet_body(kit, CA1=10)
    twice["scores"].append({"student": kit.student.pk, "component": comps["CA1"].pk, "value": 11})
    assert auth(kit.teacher).put(SHEET_URL, twice, format="json").status_code == 400
    assert not Score.objects.exists()  # nothing half-saved


def test_only_the_subject_teacher_or_admin_enters_scores(auth, kit, admin_user):
    assert enter(auth, kit, user=kit.other_teacher, Exam=50).status_code == 403
    assert enter(auth, kit, user=kit.student, Exam=50).status_code == 403
    assert enter(auth, kit, user=admin_user, Exam=50).status_code == 200


def test_form_teacher_views_but_cannot_edit_scores(auth, kit):
    make_form_teacher(kit, kit.other_teacher)
    r = auth(kit.other_teacher).get(SHEET_URL, sheet_query(kit))
    assert r.status_code == 200
    assert r.json()["can_edit"] is False
    assert enter(auth, kit, user=kit.other_teacher, Exam=50).status_code == 403


def test_another_schools_class_looks_missing(auth, kit, other_school, make_user):
    stranger = make_user("admin", school=other_school)
    r = auth(stranger).get(SHEET_URL, sheet_query(kit))
    assert r.status_code == 400  # unknown classroom/subject, not 403


# --- comments ----------------------------------------------------------------------------------


def test_comments_by_role(auth, kit, admin_user):
    make_form_teacher(kit, kit.other_teacher)
    body = {"student": kit.student.pk, "form_teacher_comment": "Steady progress."}
    assert auth(kit.teacher).put(COMMENTS_URL, body, format="json").status_code == 403
    r = auth(kit.other_teacher).put(COMMENTS_URL, body, format="json")
    assert r.status_code == 200, r.content

    principal = {"student": kit.student.pk, "principal_comment": "Well done."}
    assert auth(kit.other_teacher).put(COMMENTS_URL, principal, format="json").status_code == 403
    r = auth(admin_user).put(COMMENTS_URL, principal, format="json")
    assert r.json() == {
        "student": kit.student.pk,
        "term": kit.term.pk,
        "form_teacher_comment": "Steady progress.",
        "principal_comment": "Well done.",
    }


def test_comment_needs_a_field_and_an_enrolled_student(auth, kit, admin_user):
    client = auth(admin_user)
    assert client.put(COMMENTS_URL, {"student": kit.student.pk}, format="json").status_code == 400
    body = {"student": kit.outsider.pk, "principal_comment": "Hi"}
    assert client.put(COMMENTS_URL, body, format="json").status_code == 404


# --- drafts, publishing, locking ---------------------------------------------------------------


def test_draft_report_card_is_staff_only(auth, kit, admin_user):
    enter(auth, kit, CA1=18, CA2=17, Exam=50)
    params = {"student": kit.student.pk}
    r = auth(admin_user).get(CARD_URL, params)
    assert r.status_code == 200, r.content
    card = r.json()
    assert card["published"] is False
    assert card["subjects"][0]["total"] == "85.00" and card["subjects"][0]["grade"] == "A1"
    # the student and the subject teacher can't see unpublished results
    assert auth(kit.student).get(CARD_URL).status_code == 404
    assert auth(kit.teacher).get(CARD_URL, params).status_code == 404


def test_publish_snapshots_and_locks(auth, kit, admin_user):
    enter(auth, kit, CA1=18, CA2=17, Exam=50)
    auth(admin_user).put(
        COMMENTS_URL, {"student": kit.student.pk, "principal_comment": "Good."}, format="json"
    )
    assert auth(kit.teacher).post(PUBLISH_URL, {}).status_code == 403

    r = auth(admin_user).post(PUBLISH_URL, {})
    assert r.status_code == 202, r.content
    job = r.json()
    assert (job["kind"], job["status"], job["params"]) == (
        "publish_results",
        "done",
        {"term": kit.term.pk},
    )
    assert job["result"]["report_cards"] == 1
    assert auth(admin_user).post(PUBLISH_URL, {}).status_code == 409  # already published

    # scores and comments are locked
    assert enter(auth, kit, Exam=60).status_code == 409
    body = {"student": kit.student.pk, "principal_comment": "Changed"}
    assert auth(admin_user).put(COMMENTS_URL, body, format="json").status_code == 409
    sheet = auth(kit.teacher).get(SHEET_URL, sheet_query(kit)).json()
    assert sheet["published"] is True and sheet["can_edit"] is False

    # the student now sees the stored card
    card = auth(kit.student).get(CARD_URL).json()
    assert card["published"] is True
    assert card["summary"]["average"] == "85.00"
    assert card["comments"]["principal"] == "Good."
    assert card["grading_scale"][0]["label"] == "A1"


def test_published_card_survives_grade_scale_changes(auth, kit, admin_user):
    enter(auth, kit, CA1=18, CA2=17, Exam=50)
    auth(admin_user).post(PUBLISH_URL, {})
    kit.school.grade_bands.filter(label="A1").update(label="Excellent")
    card = auth(kit.student).get(CARD_URL).json()
    assert card["subjects"][0]["grade"] == "A1"
    assert card["grading_scale"][0]["label"] == "A1"


def test_unpublish_reopens_and_keeps_comments(auth, kit, admin_user):
    enter(auth, kit, Exam=50)
    client = auth(admin_user)
    assert client.post(UNPUBLISH_URL, {}).status_code == 409  # not published yet
    client.put(COMMENTS_URL, {"student": kit.student.pk, "principal_comment": "Ok"}, format="json")
    client.post(PUBLISH_URL, {})

    r = auth(admin_user).post(UNPUBLISH_URL, {})
    assert r.status_code == 200
    result = TermResult.objects.get(student=kit.student, term=kit.term)
    assert result.average is None and not result.subject_results.exists()
    assert result.principal_comment == "Ok"
    assert enter(auth, kit, Exam=60).status_code == 200
    assert auth(kit.student).get(CARD_URL).status_code == 404


# --- who reads a published card ----------------------------------------------------------------


def test_published_card_readers(auth, kit, admin_user, make_user):
    enter(auth, kit, Exam=50)
    auth(admin_user).post(PUBLISH_URL, {})
    params = {"student": kit.student.pk}

    parent = make_user("parent")
    Guardianship.objects.create(parent=parent, student=kit.student)
    stranger_parent = make_user("parent")

    assert auth(parent).get(CARD_URL, params).status_code == 200
    assert auth(admin_user).get(CARD_URL, params).status_code == 200
    assert auth(stranger_parent).get(CARD_URL, params).status_code == 404
    assert auth(kit.outsider).get(CARD_URL, params).status_code == 404  # a classmate's card
    assert auth(kit.teacher).get(CARD_URL, params).status_code == 404  # not the form teacher
    make_form_teacher(kit, kit.teacher)
    assert auth(kit.teacher).get(CARD_URL, params).status_code == 200


def test_staff_must_name_the_student(auth, admin_user, kit):
    assert auth(admin_user).get(CARD_URL).status_code == 404


# --- broadsheet --------------------------------------------------------------------------------


def test_class_broadsheet(auth, kit, admin_user, make_user):
    enter(auth, kit, Exam=50)
    params = {"classroom": kit.classroom.pk}
    assert auth(kit.teacher).get(CLASS_URL, params).status_code == 403
    r = auth(admin_user).get(CLASS_URL, params)
    assert r.status_code == 200, r.content
    data = r.json()
    assert data["subjects"] == ["Mathematics"]
    assert data["subject_stats"]["Mathematics"]["average"] == "50.00"
    assert data["rows"][0]["totals"] == {"Mathematics": "50.00"}
    assert data["rows"][0]["position"] == 1 and data["rows"][0]["out_of"] == 1


# --- the score split can't change under entered scores -----------------------------------------


def test_score_split_locked_once_scores_exist(auth, kit, admin_user):
    enter(auth, kit, Exam=50)
    new = {"components": [{"name": "CA", "max_score": 30}, {"name": "Exam", "max_score": 70}]}
    r = auth(admin_user).put(COMPONENTS_URL, new, format="json")
    assert r.status_code == 409
    assert kit.school.score_split(kit.session).count() == 3
    Score.objects.all().delete()
    assert auth(admin_user).put(COMPONENTS_URL, new, format="json").status_code == 200


def test_broadsheet_after_publish_matches_the_report_cards(auth, kit, admin_user):
    enter(auth, kit, CA1=18, CA2=17, Exam=50)  # 85
    auth(admin_user).post(PUBLISH_URL, {})
    # the school changes its settings after publishing
    kit.school.show_position = False
    kit.school.save()
    params = {"classroom": kit.classroom.pk}
    data = auth(admin_user).get(CLASS_URL, params).json()
    assert data["published"] is True
    assert data["rows"][0]["totals"] == {"Mathematics": "85.00"}
    assert data["rows"][0]["position"] == 1  # as printed on the card, not recomputed
    assert data["subject_stats"]["Mathematics"]["highest"] == "85.00"


# --- deleting what results depend on -----------------------------------------------------------


def test_marks_and_report_cards_block_deletes(auth, kit, admin_user):
    enter(auth, kit, Exam=50)
    client = auth(admin_user)
    subject_url = f"/api/v1/academics/subjects/{kit.subject.pk}/"
    session_url = f"/api/v1/academics/academic-sessions/{kit.session.pk}/"
    class_url = f"/api/v1/academics/classrooms/{kit.classroom.pk}/"

    assert client.delete(subject_url).status_code == 409
    assert client.delete(session_url).status_code == 409
    assert Score.objects.count() == 1  # nothing was wiped

    client.post(PUBLISH_URL, {})
    Score.objects.all().delete()  # even with no scores left, the report cards hold on
    assert client.delete(class_url).status_code == 409
    assert client.delete(session_url).status_code == 409
    assert TermResult.objects.count() == 1


def test_published_card_outlives_the_enrollment(auth, kit, admin_user, make_user):
    # a student who leaves (enrollment removed) keeps their published report cards
    enter(auth, kit, CA1=15, CA2=15, Exam=50)
    parent = make_user("parent")
    Guardianship.objects.create(parent=parent, student=kit.student)
    assert auth(admin_user).post(PUBLISH_URL, {}).status_code == 202
    kit.student.enrollments.all().delete()

    for reader in (kit.student, parent, admin_user):
        r = auth(reader).get(CARD_URL, {"student": kit.student.pk})
        assert r.status_code == 200, (reader.role, r.content)
        assert r.json()["published"] is True
