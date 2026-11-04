import pytest

from apps.academics.models import Classroom, Completion, Enrollment, Lesson, Subject
from conftest import results

pytestmark = pytest.mark.django_db


@pytest.fixture
def setup(make_user, school):
    teacher = make_user("teacher")
    student = make_user("student")
    other = make_user("student")
    classroom = Classroom.objects.create(school=school, name="8A", created_by=teacher)
    Enrollment.objects.create(classroom=classroom, student=student)
    subject = Subject.objects.create(school=school, name="Math")
    return teacher, student, other, classroom, subject


def test_teacher_can_create_classroom_and_lesson(api, auth, setup):
    teacher, _, _, classroom, subject = setup
    r = auth(teacher).post("/api/v1/academics/classrooms/", {"name": "8B"})
    assert r.status_code == 201, r.content
    r = auth(teacher).post(
        "/api/v1/academics/lessons/",
        {"title": "Fractions", "content": "1/2", "classroom": classroom.pk, "subject": subject.pk},
    )
    assert r.status_code == 201, r.content
    lesson = Lesson.objects.get(title="Fractions")
    assert lesson.created_by == teacher
    assert lesson.subject == subject


def test_student_cannot_create_lesson(api, auth, setup):
    _, student, _, classroom, subject = setup
    r = auth(student).post(
        "/api/v1/academics/lessons/",
        {"title": "Hack", "classroom": classroom.pk, "subject": subject.pk},
    )
    assert r.status_code == 403


def test_student_sees_only_enrolled_classroom_lessons(api, auth, setup):
    teacher, student, other, classroom, subject = setup
    hidden = Classroom.objects.create(school=classroom.school, name="9B", created_by=teacher)
    Lesson.objects.create(title="In 8A", classroom=classroom, subject=subject, created_by=teacher)
    Lesson.objects.create(title="In 9B", classroom=hidden, subject=subject, created_by=teacher)
    visible = results(auth(student).get("/api/v1/academics/lessons/").json())
    assert [les["title"] for les in visible] == ["In 8A"]
    other_visible = results(auth(other).get("/api/v1/academics/lessons/").json())
    assert other_visible == []
    assert results(auth(teacher).get("/api/v1/academics/lessons/").json())


def test_student_marks_lesson_complete_and_idempotent(api, auth, setup):
    teacher, student, _, classroom, subject = setup
    lesson = Lesson.objects.create(title="L", classroom=classroom, subject=subject, created_by=teacher)
    r = auth(student).post(f"/api/v1/academics/lessons/{lesson.pk}/complete/")
    assert r.status_code == 201
    r = auth(student).post(f"/api/v1/academics/lessons/{lesson.pk}/complete/")
    assert r.status_code == 200
    assert Completion.objects.count() == 1


def test_teacher_cannot_complete_lesson(api, auth, setup):
    teacher, _, _, classroom, subject = setup
    lesson = Lesson.objects.create(title="L", classroom=classroom, subject=subject, created_by=teacher)
    assert auth(teacher).post(f"/api/v1/academics/lessons/{lesson.pk}/complete/").status_code == 403


def test_enrollment_only_accepts_students(api, auth, setup):
    teacher, student, other, classroom, _ = setup
    r = auth(teacher).post("/api/v1/academics/enrollments/", {"classroom": classroom.pk, "student": other.pk})
    assert r.status_code == 201
    r = auth(teacher).post(
        "/api/v1/academics/enrollments/", {"classroom": classroom.pk, "student": teacher.pk}
    )
    assert r.status_code == 400
    # duplicate enrollment rejected by constraint
    r = auth(teacher).post("/api/v1/academics/enrollments/", {"classroom": classroom.pk, "student": student.pk})
    assert r.status_code == 400


def test_progress_counts(api, auth, setup):
    teacher, student, other, classroom, subject = setup
    lesson = Lesson.objects.create(title="L", classroom=classroom, subject=subject, created_by=teacher)
    Completion.objects.create(lesson=lesson, student=student)
    data = auth(student).get("/api/v1/academics/progress/").json()
    assert data["classrooms"][0]["lessons"] == {"total": 1, "completed": 1}
    assert data["classrooms"][0]["quizzes"]["submitted"] == 0


def test_progress_quizzes_exclude_assignments(api, auth, setup):
    from apps.assessments.models import Assessment, Submission

    teacher, student, other, classroom, subject = setup
    quiz = Assessment.objects.create(
        title="Q", type="quiz", classroom=classroom, subject=subject, created_by=teacher,
        max_points=2,
    )
    essay = Assessment.objects.create(
        title="E", type="assignment", classroom=classroom, subject=subject, created_by=teacher
    )
    Submission.objects.create(assessment=quiz, student=student, score=2)
    Submission.objects.create(assessment=essay, student=student, score=8)
    data = auth(student).get("/api/v1/academics/progress/").json()
    quizzes = data["classrooms"][0]["quizzes"]
    assert quizzes["total"] == 1  # essay not counted as quiz
    assert quizzes["submitted"] == 1
    assert quizzes["avg_score_pct"] == 100.0  # 2/2 from the quiz only
