import pytest

from apps.academics.models import Subject
from apps.assessments.models import Assessment, Submission
from conftest import assign, make_classroom, results

pytestmark = pytest.mark.django_db

ASSESSMENTS_URL = "/api/v1/assessments/"
SUBMISSIONS_URL = "/api/v1/submissions/"

QUIZ_PAYLOAD = {
    "title": "Algebra basics",
    "type": "quiz",
    "questions": [
        {
            "text": "1+1?",
            "points": 2,
            "choices": [
                {"text": "1", "is_correct": False},
                {"text": "2", "is_correct": True},
            ],
        },
        {
            "text": "2+2?",
            "choices": [
                {"text": "3", "is_correct": False},
                {"text": "4", "is_correct": True},
            ],
        },
    ],
}


def create_quiz(client, kit):
    payload = {**QUIZ_PAYLOAD, "classroom": kit.classroom.pk, "subject": kit.subject.pk}
    r = client.post(ASSESSMENTS_URL, payload, format="json")
    assert r.status_code == 201, r.content
    return Assessment.objects.get(pk=r.data["id"])


def make_assignment(kit, title="Essay", classroom=None):
    return Assessment.objects.create(
        title=title,
        type="assignment",
        classroom=classroom or kit.classroom,
        subject=kit.subject,
        term=kit.term,
        created_by=kit.teacher,
        max_points=10,
    )


def test_teacher_creates_quiz_with_nested_questions(auth, kit):
    quiz = create_quiz(auth(kit.teacher), kit)
    assert quiz.max_points == 3  # 2 + 1
    assert quiz.questions.count() == 2
    assert quiz.term == kit.term
    assert quiz.questions.first().choices.filter(is_correct=True).count() == 1


def test_only_the_subjects_teacher_creates_quizzes(auth, kit):
    payload = {**QUIZ_PAYLOAD, "classroom": kit.classroom.pk, "subject": kit.subject.pk}
    r = auth(kit.other_teacher).post(ASSESSMENTS_URL, payload, format="json")
    assert r.status_code == 403
    assert not Assessment.objects.exists()


def test_only_the_subjects_teacher_edits_quizzes(auth, kit, admin_user):
    quiz = create_quiz(auth(kit.teacher), kit)
    url = f"{ASSESSMENTS_URL}{quiz.pk}/"
    # other teachers don't see the quiz at all (it carries the answer key)
    assert auth(kit.other_teacher).patch(url, {"title": "X"}, format="json").status_code == 404
    assert auth(kit.other_teacher).delete(url).status_code == 404
    assert auth(kit.teacher).patch(url, {"title": "Y"}, format="json").status_code == 200
    assert auth(admin_user).delete(url).status_code == 204


def test_student_cannot_see_correct_answers(auth, kit):
    quiz = create_quiz(auth(kit.teacher), kit)
    data = auth(kit.student).get(f"{ASSESSMENTS_URL}{quiz.pk}/").json()
    assert "is_correct" not in str(data["questions"][0]["choices"])
    teacher_view = auth(kit.teacher).get(f"{ASSESSMENTS_URL}{quiz.pk}/").json()
    assert teacher_view["questions"][0]["choices"][0]["is_correct"] is False


def test_parents_cannot_see_quizzes_or_answers(auth, kit, make_user):
    create_quiz(auth(kit.teacher), kit)
    assert results(auth(make_user("parent")).get(ASSESSMENTS_URL).json()) == []


def test_student_submit_auto_grades_quiz(auth, kit):
    quiz = create_quiz(auth(kit.teacher), kit)
    q1, q2 = quiz.questions.order_by("id")
    c1 = q1.choices.get(is_correct=True)
    c2 = q2.choices.get(is_correct=False)
    r = auth(kit.student).post(
        f"{ASSESSMENTS_URL}{quiz.pk}/submit/",
        {"answers": [{"question": q1.pk, "choice": c1.pk}, {"question": q2.pk, "choice": c2.pk}]},
        format="json",
    )
    assert r.status_code == 201, r.content
    assert r.data["score"] == 2  # q1 correct (2 pts), q2 wrong (1 pt)


def test_double_submit_rejected(auth, kit):
    quiz = create_quiz(auth(kit.teacher), kit)
    q1, q2 = quiz.questions.order_by("id")
    body = {
        "answers": [
            {"question": q1.pk, "choice": q1.choices.get(is_correct=True).pk},
            {"question": q2.pk, "choice": q2.choices.get(is_correct=True).pk},
        ]
    }
    url = f"{ASSESSMENTS_URL}{quiz.pk}/submit/"
    assert auth(kit.student).post(url, body, format="json").status_code == 201
    assert auth(kit.student).post(url, body, format="json").status_code == 409


def test_outsider_cannot_see_or_submit_quiz(auth, kit):
    quiz = create_quiz(auth(kit.teacher), kit)
    assert auth(kit.outsider).get(f"{ASSESSMENTS_URL}{quiz.pk}/").status_code == 404
    q = quiz.questions.first()
    r = auth(kit.outsider).post(
        f"{ASSESSMENTS_URL}{quiz.pk}/submit/",
        {"answers": [{"question": q.pk, "choice": q.choices.first().pk}]},
        format="json",
    )
    assert r.status_code == 404


def test_submit_validates_answer_belongs_to_quiz(auth, kit):
    quiz = create_quiz(auth(kit.teacher), kit)
    other_quiz = create_quiz(auth(kit.teacher), kit)
    q = other_quiz.questions.first()
    r = auth(kit.student).post(
        f"{ASSESSMENTS_URL}{quiz.pk}/submit/",
        {"answers": [{"question": q.pk, "choice": q.choices.first().pk}]},
        format="json",
    )
    assert r.status_code == 400


def test_assignment_flow_submit_and_teacher_grades(auth, kit):
    r = auth(kit.teacher).post(
        ASSESSMENTS_URL,
        {
            "title": "Essay",
            "type": "assignment",
            "classroom": kit.classroom.pk,
            "subject": kit.subject.pk,
            "max_points": 10,
        },
        format="json",
    )
    assert r.status_code == 201, r.content
    r = auth(kit.student).post(f"{ASSESSMENTS_URL}{r.data['id']}/submit/", {"text": "My essay"})
    assert r.status_code == 201, r.content
    assert r.data["score"] is None
    url = f"{SUBMISSIONS_URL}{r.data['id']}/"
    assert auth(kit.student).patch(url, {"score": 8}).status_code == 403
    r = auth(kit.teacher).patch(url, {"score": 8})
    assert r.status_code == 200, r.content
    assert r.data["score"] == 8 and r.data["graded_at"]
    assert auth(kit.teacher).patch(url, {"score": 99}).status_code == 400


def test_assignment_requires_text_or_file(auth, kit):
    essay = make_assignment(kit)
    assert auth(kit.student).post(f"{ASSESSMENTS_URL}{essay.pk}/submit/", {}).status_code == 400


# --- who sees and grades submissions ----------------------------------------------------------


def test_student_sees_only_own_submissions(auth, kit):
    essay = make_assignment(kit)
    Submission.objects.create(assessment=essay, student=kit.student, text="mine")
    mine = results(auth(kit.student).get(SUBMISSIONS_URL).json())
    assert len(mine) == 1 and mine[0]["student"] == kit.student.pk
    assert results(auth(kit.outsider).get(SUBMISSIONS_URL).json()) == []
    rows = results(auth(kit.teacher).get(f"{SUBMISSIONS_URL}?assessment={essay.pk}").json())
    assert len(rows) == 1


def test_teachers_see_submissions_only_for_what_they_teach(auth, kit):
    Submission.objects.create(assessment=make_assignment(kit), student=kit.student, text="x")
    assert results(auth(kit.other_teacher).get(SUBMISSIONS_URL).json()) == []
    # teaching another subject in the same class doesn't help
    english = Subject.objects.create(school=kit.school, name="English")
    assign(kit.other_teacher, kit.classroom, english)
    assert results(auth(kit.other_teacher).get(SUBMISSIONS_URL).json()) == []


def test_form_teacher_sees_but_cannot_grade(auth, kit):
    submission = Submission.objects.create(
        assessment=make_assignment(kit), student=kit.student, text="x"
    )
    kit.classroom.form_teacher = kit.other_teacher
    kit.classroom.save()
    rows = results(auth(kit.other_teacher).get(SUBMISSIONS_URL).json())
    assert [s["id"] for s in rows] == [submission.pk]
    r = auth(kit.other_teacher).patch(f"{SUBMISSIONS_URL}{submission.pk}/", {"score": 5})
    assert r.status_code == 403


def test_admin_grades_anything(auth, kit, admin_user):
    submission = Submission.objects.create(
        assessment=make_assignment(kit), student=kit.student, text="x"
    )
    r = auth(admin_user).patch(f"{SUBMISSIONS_URL}{submission.pk}/", {"score": 6})
    assert r.status_code == 200 and r.data["score"] == 6


def test_assessments_filter_by_classroom(auth, kit, admin_user):
    make_assignment(kit)
    other_class = make_classroom(kit.school, "B")
    make_assignment(kit, "B work", classroom=other_class)
    rows = results(auth(admin_user).get(f"{ASSESSMENTS_URL}?classroom={other_class.pk}").json())
    assert [a["title"] for a in rows] == ["B work"]


# --- uploads ---------------------------------------------------------------------------------


def test_submission_files_are_checked(auth, kit, settings, tmp_path):
    from django.core.files.uploadedfile import SimpleUploadedFile

    settings.MEDIA_ROOT = tmp_path
    essay = make_assignment(kit)
    url = f"{ASSESSMENTS_URL}{essay.pk}/submit/"
    client = auth(kit.student)

    script = SimpleUploadedFile("essay.exe", b"MZ...", content_type="application/octet-stream")
    r = client.post(url, {"file": script}, format="multipart")
    assert r.status_code == 400 and "file" in r.json()

    huge = SimpleUploadedFile("essay.pdf", b"0" * (10 * 1024 * 1024 + 1))
    r = client.post(url, {"file": huge}, format="multipart")
    assert r.status_code == 400 and "10 MB" in str(r.json())

    ok = SimpleUploadedFile("essay.pdf", b"%PDF-1.7 ...", content_type="application/pdf")
    assert client.post(url, {"file": ok}, format="multipart").status_code == 201


# --- integrity -------------------------------------------------------------------------------


def test_answer_keys_only_for_what_you_teach(auth, kit):
    quiz = create_quiz(auth(kit.teacher), kit)
    others = results(auth(kit.other_teacher).get(ASSESSMENTS_URL).json())
    assert others == []
    assert auth(kit.other_teacher).get(f"{ASSESSMENTS_URL}{quiz.pk}/").status_code == 404
    # the class's form teacher can see its work
    kit.classroom.form_teacher = kit.other_teacher
    kit.classroom.save()
    assert len(results(auth(kit.other_teacher).get(ASSESSMENTS_URL).json())) == 1


def test_quiz_questions_need_a_single_right_answer(auth, kit):
    def payload(choices):
        question = {"text": "Q", "choices": choices}
        return {
            **QUIZ_PAYLOAD,
            "questions": [question],
            "classroom": kit.classroom.pk,
            "subject": kit.subject.pk,
        }

    client = auth(kit.teacher)
    one_choice = payload([{"text": "a", "is_correct": True}])
    none_right = payload([{"text": "a", "is_correct": False}, {"text": "b", "is_correct": False}])
    two_right = payload([{"text": "a", "is_correct": True}, {"text": "b", "is_correct": True}])
    for body in (one_choice, none_right, two_right):
        r = client.post(ASSESSMENTS_URL, body, format="json")
        assert r.status_code == 400 and "questions" in r.json(), r.content


def test_assessment_type_is_fixed(auth, kit):
    quiz = create_quiz(auth(kit.teacher), kit)
    r = auth(kit.teacher).patch(f"{ASSESSMENTS_URL}{quiz.pk}/", {"type": "assignment"})
    assert r.status_code == 400 and "type" in r.json()
    r = auth(kit.teacher).patch(f"{ASSESSMENTS_URL}{quiz.pk}/", {"title": "Renamed"})
    assert r.status_code == 200


def test_late_submissions_are_flagged(auth, kit):
    from datetime import timedelta

    from django.utils import timezone

    essay = make_assignment(kit)
    essay.due_at = timezone.now() - timedelta(hours=1)
    essay.save()
    r = auth(kit.student).post(f"{ASSESSMENTS_URL}{essay.pk}/submit/", {"text": "Sorry, late"})
    assert r.status_code == 201 and r.json()["is_late"] is True
