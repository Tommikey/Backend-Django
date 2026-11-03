import pytest

from apps.academics.models import Classroom, Enrollment, Subject
from apps.assessments.models import Assessment
from conftest import results

pytestmark = pytest.mark.django_db

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


@pytest.fixture
def setup(make_user):
    teacher = make_user("teacher")
    student = make_user("student")
    outsider = make_user("student")
    classroom = Classroom.objects.create(name="8A", created_by=teacher)
    Enrollment.objects.create(classroom=classroom, student=student)
    subject = Subject.objects.create(name="Math")
    return teacher, student, outsider, classroom, subject


def create_quiz(api, teacher, classroom, subject):
    payload = {**QUIZ_PAYLOAD, "classroom": classroom.pk, "subject": subject.pk}
    r = api.post("/api/v1/assessments/", payload, format="json")
    assert r.status_code == 201, r.content
    return Assessment.objects.get(pk=r.data["id"])


def test_teacher_creates_quiz_with_nested_questions(api, auth, setup):
    teacher, _, _, classroom, subject = setup
    quiz = create_quiz(auth(teacher), teacher, classroom, subject)
    assert quiz.max_points == 3  # 2 + 1
    assert quiz.questions.count() == 2
    assert quiz.questions.first().choices.filter(is_correct=True).count() == 1


def test_student_cannot_see_correct_answers(api, auth, setup):
    teacher, student, _, classroom, subject = setup
    quiz = create_quiz(auth(teacher), teacher, classroom, subject)
    data = auth(student).get(f"/api/v1/assessments/{quiz.pk}/").json()
    assert "is_correct" not in str(data["questions"][0]["choices"])
    teacher_view = auth(teacher).get(f"/api/v1/assessments/{quiz.pk}/").json()
    assert teacher_view["questions"][0]["choices"][0]["is_correct"] is False


def test_student_submit_auto_grades_quiz(api, auth, setup):
    teacher, student, _, classroom, subject = setup
    quiz = create_quiz(auth(teacher), teacher, classroom, subject)
    q1, q2 = quiz.questions.order_by("id")
    c1 = q1.choices.get(is_correct=True)
    c2 = q2.choices.get(is_correct=False)
    r = auth(student).post(
        f"/api/v1/assessments/{quiz.pk}/submit/",
        {"answers": [{"question": q1.pk, "choice": c1.pk}, {"question": q2.pk, "choice": c2.pk}]},
        format="json",
    )
    assert r.status_code == 201, r.content
    assert r.data["score"] == 2  # q1 correct (2 pts), q2 wrong (1 pt)


def test_double_submit_rejected(api, auth, setup):
    teacher, student, _, classroom, subject = setup
    quiz = create_quiz(auth(teacher), teacher, classroom, subject)
    q1, q2 = quiz.questions.order_by("id")
    c1 = q1.choices.get(is_correct=True)
    c2 = q2.choices.get(is_correct=True)
    body = {"answers": [{"question": q1.pk, "choice": c1.pk}, {"question": q2.pk, "choice": c2.pk}]}
    assert auth(student).post(f"/api/v1/assessments/{quiz.pk}/submit/", body, format="json").status_code == 201
    assert auth(student).post(f"/api/v1/assessments/{quiz.pk}/submit/", body, format="json").status_code == 409


def test_outsider_cannot_see_or_submit_quiz(api, auth, setup):
    teacher, student, outsider, classroom, subject = setup
    quiz = create_quiz(auth(teacher), teacher, classroom, subject)
    assert auth(outsider).get(f"/api/v1/assessments/{quiz.pk}/").status_code == 404
    q = quiz.questions.first()
    c = q.choices.first()
    r = auth(outsider).post(
        f"/api/v1/assessments/{quiz.pk}/submit/",
        {"answers": [{"question": q.pk, "choice": c.pk}]},
        format="json",
    )
    assert r.status_code == 404


def test_submit_validates_answer_belongs_to_quiz(api, auth, setup):
    teacher, student, _, classroom, subject = setup
    quiz = create_quiz(auth(teacher), teacher, classroom, subject)
    other_quiz = Assessment.objects.create(
        title="Other", type="quiz", classroom=classroom, subject=subject, created_by=teacher
    )
    q = other_quiz.questions.create(text="?", points=1)
    q.choices.create(text="x", is_correct=True)
    r = auth(student).post(
        f"/api/v1/assessments/{quiz.pk}/submit/",
        {"answers": [{"question": q.pk, "choice": q.choices.first().pk}]},
        format="json",
    )
    assert r.status_code == 400


def test_assignment_flow_submit_and_teacher_grades(api, auth, setup):
    teacher, student, _, classroom, subject = setup
    r = auth(teacher).post(
        "/api/v1/assessments/",
        {
            "title": "Essay",
            "type": "assignment",
            "classroom": classroom.pk,
            "subject": subject.pk,
            "max_points": 10,
        },
        format="json",
    )
    assignment = r.data["id"]
    r = auth(student).post(f"/api/v1/assessments/{assignment}/submit/", {"text": "My essay"})
    assert r.status_code == 201, r.content
    assert r.data["score"] is None
    sid = r.data["id"]
    r = auth(student).patch(f"/api/v1/submissions/{sid}/", {"score": 8})
    assert r.status_code == 403
    r = auth(teacher).patch(f"/api/v1/submissions/{sid}/", {"score": 8})
    assert r.status_code == 200, r.content
    assert r.data["score"] == 8
    assert r.data["graded_at"]
    r = auth(teacher).patch(f"/api/v1/submissions/{sid}/", {"score": 99})
    assert r.status_code == 400


def test_assignment_requires_text_or_file(api, auth, setup):
    teacher, student, _, classroom, subject = setup
    r = auth(teacher).post(
        "/api/v1/assessments/",
        {"title": "HW", "type": "assignment", "classroom": classroom.pk, "subject": subject.pk},
    )
    assignment = r.data["id"]
    assert auth(student).post(f"/api/v1/assessments/{assignment}/submit/", {}).status_code == 400


def test_student_sees_only_own_submissions(api, auth, setup):
    teacher, student, outsider, classroom, subject = setup
    assignment = Assessment.objects.create(
        title="HW", type="assignment", classroom=classroom, subject=subject, created_by=teacher
    )
    from apps.assessments.models import Submission

    Submission.objects.create(assessment=assignment, student=student, text="mine")
    mine = results(auth(student).get("/api/v1/submissions/").json())
    assert len(mine) == 1 and mine[0]["student"] == student.pk
    assert results(auth(outsider).get("/api/v1/submissions/").json()) == []
    all_subs = results(auth(teacher).get(f"/api/v1/submissions/?assessment={assignment.pk}").json())
    assert len(all_subs) == 1
