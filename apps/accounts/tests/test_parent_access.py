"""Parents see what their children see, read-only: lessons, assessments (without answer keys),
their submissions and grades, live classes, classes and teachers. Nothing of other children."""

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.academics.models import Lesson
from apps.academics.services import create_session
from apps.accounts.models import Guardianship
from apps.assessments.models import Assessment, Choice, Question, Submission
from apps.live_classes.models import LiveClass
from conftest import enroll, make_classroom, results

pytestmark = pytest.mark.django_db


@pytest.fixture
def family(kit, make_user):
    """kit's student (Ada, JSS1A) and a sibling in JSS1B, both linked to one parent; a quiz,
    a lesson and a live class for each class; Ada has submitted the quiz."""
    sibling_class = make_classroom(kit.school, "B")
    sibling = make_user("student")
    enroll(sibling, sibling_class)
    parent = make_user("parent")
    for child in (kit.student, sibling):
        Guardianship.objects.create(parent=parent, student=child)

    def material(classroom, tag):
        common = {"classroom": classroom, "subject": kit.subject, "term": kit.term}
        quiz = Assessment.objects.create(title=f"Quiz {tag}", type="quiz", max_points=1, **common)
        question = Question.objects.create(assessment=quiz, text="1+1?", points=1)
        Choice.objects.create(question=question, text="2", is_correct=True)
        Choice.objects.create(question=question, text="3", is_correct=False)
        Lesson.objects.create(title=f"Lesson {tag}", **common)
        LiveClass.objects.create(
            title=f"Live {tag}",
            starts_at=timezone.now() + timedelta(days=1),
            join_url="https://x.org/j",
            **common,
        )
        return quiz

    quiz_a = material(kit.classroom, "A")
    material(sibling_class, "B")
    Submission.objects.create(assessment=quiz_a, student=kit.student, score=1)
    kit.sibling, kit.sibling_class, kit.parent = sibling, sibling_class, parent
    return kit


def titles(response):
    assert response.status_code == 200, response.content
    return sorted(row["title"] for row in results(response.json()))


def test_parent_sees_both_childrens_work(auth, family):
    client = auth(family.parent)
    assert titles(client.get("/api/v1/academics/lessons/")) == ["Lesson A", "Lesson B"]
    assert titles(client.get("/api/v1/assessments/")) == ["Quiz A", "Quiz B"]
    assert titles(client.get("/api/v1/live-classes/")) == ["Live A", "Live B"]
    subs = results(client.get("/api/v1/submissions/").json())
    assert [(s["student"], s["score"]) for s in subs] == [(family.student.pk, 1.0)]


def test_no_answer_keys_for_parents(auth, family):
    rows = results(auth(family.parent).get("/api/v1/assessments/").json())
    assert rows and all(
        "is_correct" not in choice for q in rows[0]["questions"] for choice in q["choices"]
    )


def test_child_filter(auth, family):
    client = auth(family.parent)
    only_b = client.get("/api/v1/assessments/", {"child": family.sibling.pk})
    assert titles(only_b) == ["Quiz B"]
    classes = results(
        client.get("/api/v1/academics/classrooms/", {"child": family.student.pk}).json()
    )
    assert [c["name"] for c in classes] == ["JSS1A"]
    # someone else's child: nothing, not an error that confirms they exist
    assert titles(client.get("/api/v1/academics/lessons/", {"child": family.outsider.pk})) == []
    assert client.get("/api/v1/academics/lessons/", {"child": "x"}).status_code == 400


def test_classes_enrollments_and_teachers(auth, family):
    client = auth(family.parent)
    classes = results(client.get("/api/v1/academics/classrooms/").json())
    assert sorted(c["name"] for c in classes) == ["JSS1A", "JSS1B"]
    enrollments = results(client.get("/api/v1/academics/enrollments/").json())
    assert {e["student"] for e in enrollments} == {family.student.pk, family.sibling.pk}
    teaching = results(client.get("/api/v1/academics/teaching-assignments/").json())
    assert [(t["classroom_name"], t["teacher_name"]) for t in teaching] == [
        ("JSS1A", family.teacher.display_name)
    ]


def test_only_their_childrens_sessions(auth, family):
    # a lesson in JSS1A next year: Ada isn't enrolled then, so her parent doesn't see it
    following = create_session(family.school, "2026/2027")
    Lesson.objects.create(
        title="Next year",
        classroom=family.classroom,
        subject=family.subject,
        term=following.terms.first(),
    )
    assert "Next year" not in titles(auth(family.parent).get("/api/v1/academics/lessons/"))


def test_other_parents_see_nothing(auth, family, make_user):
    stranger = auth(make_user("parent"))
    for url in (
        "/api/v1/academics/lessons/",
        "/api/v1/assessments/",
        "/api/v1/submissions/",
        "/api/v1/live-classes/",
        "/api/v1/academics/classrooms/",
        "/api/v1/academics/enrollments/",
        "/api/v1/academics/teaching-assignments/",
    ):
        assert results(stranger.get(url).json()) == [], url


def test_parents_cannot_act_for_their_children(auth, family):
    client = auth(family.parent)
    quiz = Assessment.objects.get(title="Quiz B")
    lesson = Lesson.objects.get(title="Lesson B")
    assert client.post(f"/api/v1/assessments/{quiz.pk}/submit/", {}).status_code == 403
    assert client.post(f"/api/v1/academics/lessons/{lesson.pk}/complete/").status_code == 403
    assert client.patch(f"/api/v1/assessments/{quiz.pk}/", {"title": "x"}).status_code == 403
    sub = Submission.objects.get(student=family.student)
    assert client.patch(f"/api/v1/submissions/{sub.pk}/", {"score": 0}).status_code == 403


def test_students_see_who_teaches_them(auth, family):
    rows = results(auth(family.student).get("/api/v1/academics/teaching-assignments/").json())
    assert [t["classroom_name"] for t in rows] == ["JSS1A"]
    assert results(auth(family.sibling).get("/api/v1/academics/teaching-assignments/").json()) == []
