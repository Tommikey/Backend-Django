"""Lessons follow teaching assignments; students see their class for the session; progress."""

import pytest

from apps.academics.models import AcademicSession, Completion, Lesson, Subject, Term
from apps.academics.services import create_session
from apps.assessments.models import Assessment, Submission
from conftest import assign, enroll, make_classroom, results

pytestmark = pytest.mark.django_db

LESSONS_URL = "/api/v1/academics/lessons/"


def lesson_body(kit, **extra):
    return {
        "title": "Fractions",
        "content": "1/2",
        "classroom": kit.classroom.pk,
        "subject": kit.subject.pk,
        **extra,
    }


def make_lesson(kit, title="L", classroom=None, term=None):
    return Lesson.objects.create(
        title=title,
        classroom=classroom or kit.classroom,
        subject=kit.subject,
        term=term or kit.term,
        created_by=kit.teacher,
    )


# --- who may post ------------------------------------------------------------------------------


def test_assigned_teacher_posts_lesson_in_current_term(auth, kit):
    r = auth(kit.teacher).post(LESSONS_URL, lesson_body(kit))
    assert r.status_code == 201, r.content
    lesson = Lesson.objects.get(title="Fractions")
    assert lesson.created_by == kit.teacher
    assert lesson.term == kit.term
    assert r.json()["term_name"] == "First Term"


def test_unassigned_teacher_cannot_post(auth, kit):
    r = auth(kit.other_teacher).post(LESSONS_URL, lesson_body(kit))
    assert r.status_code == 403
    assert "don't teach Mathematics to JSS1A" in r.json()["detail"]


def test_teacher_cannot_post_other_subjects_in_own_class(auth, kit):
    english = Subject.objects.create(school=kit.school, name="English")
    r = auth(kit.teacher).post(LESSONS_URL, lesson_body(kit, subject=english.pk))
    assert r.status_code == 403


def test_assignment_is_per_session(auth, kit):
    """Teaching JSS1A maths this session gives no rights in another session's terms."""
    old = create_session(kit.school, "2024/2025")
    old_term = old.terms.get(order=1)
    r = auth(kit.teacher).post(LESSONS_URL, lesson_body(kit, term=old_term.pk))
    assert r.status_code == 403


def test_teacher_cannot_move_lesson_out_of_what_they_teach(auth, kit):
    lesson = make_lesson(kit)
    jss1b = make_classroom(kit.school, "B")
    r = auth(kit.teacher).patch(f"{LESSONS_URL}{lesson.pk}/", {"classroom": jss1b.pk})
    assert r.status_code == 403
    lesson.refresh_from_db()
    assert lesson.classroom == kit.classroom


def test_edit_rights_follow_the_assignment_not_the_author(auth, kit, admin_user):
    lesson = make_lesson(kit)
    url = f"{LESSONS_URL}{lesson.pk}/"
    assert auth(kit.other_teacher).patch(url, {"title": "X"}).status_code == 403
    assert auth(kit.other_teacher).delete(url).status_code == 403
    # the subject is handed over: the new teacher can now edit the old lesson
    kit.classroom.teaching_assignments.update(teacher=kit.other_teacher)
    assert auth(kit.other_teacher).patch(url, {"title": "Taken over"}).status_code == 200
    assert auth(kit.teacher).patch(url, {"title": "X"}).status_code == 403
    assert auth(admin_user).patch(url, {"title": "By admin"}).status_code == 200


def test_students_and_parents_cannot_post(auth, kit, make_user):
    assert auth(kit.student).post(LESSONS_URL, lesson_body(kit)).status_code == 403
    assert auth(make_user("parent")).post(LESSONS_URL, lesson_body(kit)).status_code == 403


def test_without_current_term_a_term_must_be_given(auth, kit):
    Term.objects.update(is_current=False)
    r = auth(kit.teacher).post(LESSONS_URL, lesson_body(kit))
    assert r.status_code == 400
    assert "no current term" in str(r.json())
    r = auth(kit.teacher).post(LESSONS_URL, lesson_body(kit, term=kit.term.pk))
    assert r.status_code == 201


# --- who sees what -------------------------------------------------------------------------------


def test_student_sees_only_their_class_lessons(auth, kit):
    make_lesson(kit, "In JSS1A")
    make_lesson(kit, "In JSS1B", classroom=make_classroom(kit.school, "B"))
    visible = results(auth(kit.student).get(LESSONS_URL).json())
    assert [lesson["title"] for lesson in visible] == ["In JSS1A"]
    assert results(auth(kit.outsider).get(LESSONS_URL).json()) == []
    assert len(results(auth(kit.teacher).get(LESSONS_URL).json())) == 2


def test_last_years_class_does_not_leak_this_years_lessons(auth, kit):
    """A student who was in JSS1A last session and moved on doesn't see JSS1A's new lessons."""
    last_year = create_session(kit.school, "2024/2025")
    enroll(kit.outsider, kit.classroom, session=last_year)  # in JSS1A last year only
    make_lesson(kit, "This year")
    make_lesson(kit, "Last year", term=last_year.terms.get(order=1))
    visible = results(auth(kit.outsider).get(LESSONS_URL).json())
    assert [lesson["title"] for lesson in visible] == ["Last year"]


def test_parents_see_no_lessons_yet(auth, kit, make_user):
    make_lesson(kit)
    assert results(auth(make_user("parent")).get(LESSONS_URL).json()) == []


def test_lessons_filter_by_term(auth, kit):
    make_lesson(kit, "First")
    second = kit.session.terms.get(order=2)
    make_lesson(kit, "Second", term=second)
    rows = results(auth(kit.teacher).get(f"{LESSONS_URL}?term={second.pk}").json())
    assert [lesson["title"] for lesson in rows] == ["Second"]


# --- completing lessons ----------------------------------------------------------------------------


def test_student_marks_lesson_complete_and_idempotent(auth, kit):
    lesson = make_lesson(kit)
    assert auth(kit.student).post(f"{LESSONS_URL}{lesson.pk}/complete/").status_code == 201
    assert auth(kit.student).post(f"{LESSONS_URL}{lesson.pk}/complete/").status_code == 200
    assert Completion.objects.count() == 1


def test_teacher_cannot_complete_lesson(auth, kit):
    lesson = make_lesson(kit)
    assert auth(kit.teacher).post(f"{LESSONS_URL}{lesson.pk}/complete/").status_code == 403


# --- progress --------------------------------------------------------------------------------------

PROGRESS_URL = "/api/v1/academics/progress/"


def class_names(response):
    return [c["classroom"]["name"] for c in response.json()["classrooms"]]


def test_progress_counts_for_the_current_session(auth, kit):
    lesson = make_lesson(kit)
    Completion.objects.create(lesson=lesson, student=kit.student)
    make_lesson(kit, "Old", term=create_session(kit.school, "2024/2025").terms.first())
    data = auth(kit.student).get(PROGRESS_URL).json()
    assert data["session"]["name"] == "2025/2026"
    [row] = data["classrooms"]
    assert row["classroom"]["name"] == "JSS1A"
    assert row["students"] == 1
    assert row["lessons"] == {"total": 1, "completed": 1}  # last session's lesson not counted


def test_progress_quizzes_exclude_assignments(auth, kit):
    common = {"classroom": kit.classroom, "subject": kit.subject, "term": kit.term}
    quiz = Assessment.objects.create(title="Q", type="quiz", max_points=2, **common)
    essay = Assessment.objects.create(title="E", type="assignment", **common)
    Submission.objects.create(assessment=quiz, student=kit.student, score=2)
    Submission.objects.create(assessment=essay, student=kit.student, score=8)
    quizzes = auth(kit.student).get(PROGRESS_URL).json()["classrooms"][0]["quizzes"]
    assert quizzes == {"total": 1, "submitted": 1, "avg_score_pct": 100.0}


def test_progress_shows_teachers_their_classes(auth, kit):
    make_classroom(kit.school, "B")  # nobody's
    form_class = make_classroom(kit.school, "C")
    form_class.form_teacher = kit.other_teacher
    form_class.save()
    assert class_names(auth(kit.teacher).get(PROGRESS_URL)) == ["JSS1A"]
    assert class_names(auth(kit.other_teacher).get(PROGRESS_URL)) == ["JSS1C"]


def test_teacher_of_another_subject_also_sees_the_class(auth, kit):
    english = Subject.objects.create(school=kit.school, name="English")
    assign(kit.other_teacher, kit.classroom, english)
    assert class_names(auth(kit.other_teacher).get(PROGRESS_URL)) == ["JSS1A"]


def test_progress_without_a_session(auth, kit):
    AcademicSession.objects.update(is_current=False)
    assert auth(kit.student).get(PROGRESS_URL).json() == {"session": None, "classrooms": []}


def test_lesson_files_are_checked(auth, kit, settings, tmp_path):
    from django.core.files.uploadedfile import SimpleUploadedFile

    settings.MEDIA_ROOT = tmp_path
    bad = SimpleUploadedFile("notes.html", b"<script>alert(1)</script>", content_type="text/html")
    r = auth(kit.teacher).post(LESSONS_URL, {**lesson_body(kit), "file": bad}, format="multipart")
    assert r.status_code == 400 and "file" in r.json()
    good = SimpleUploadedFile("notes.pdf", b"%PDF-1.7", content_type="application/pdf")
    r = auth(kit.teacher).post(LESSONS_URL, {**lesson_body(kit), "file": good}, format="multipart")
    assert r.status_code == 201, r.content
