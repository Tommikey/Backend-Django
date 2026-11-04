"""Demo data: one school per system, each with a running school year. Safe to re-run."""

from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.academics.models import (
    Classroom,
    Completion,
    Enrollment,
    Lesson,
    Subject,
    TeachingAssignment,
)
from apps.academics.services import create_session
from apps.accounts.models import Guardianship, User
from apps.assessments.models import Answer, Assessment, Choice, Question, Submission
from apps.live_classes.models import LiveClass
from apps.results.models import Score, TermResult
from apps.schools.models import School
from apps.schools.services import onboard_school

PASSWORD = "pass1234"

DEMO_SCHOOLS = [
    # (slug, name, system, username prefix)
    ("demo-secondary-school", "Demo Secondary School", School.System.NG, ""),
    ("demo-academy", "Demo Academy", School.System.UK, "uk_"),
    ("demo-high-school", "Demo High School", School.System.US, "us_"),
]


class Command(BaseCommand):
    help = "Create demo schools (Nigerian, British, US) for local development. Safe to re-run."

    def handle(self, *args, **options):
        # platform staff: Django admin only, belongs to no school
        platform, _ = User.objects.get_or_create(
            username="platform",
            defaults={"email": "platform@yap.school", "is_staff": True, "is_superuser": True},
        )
        platform.set_password(PASSWORD)
        platform.save()

        for slug, name, system, prefix in DEMO_SCHOOLS:
            if School.objects.filter(slug=slug).exists():
                self.stdout.write(f"  {name}: already there, skipped")
                continue
            build_school(slug, name, system, prefix)
            self.stdout.write(f"  {name}: created")

        self.stdout.write(self.style.SUCCESS(f"Seed complete. Every password is {PASSWORD}"))
        for _, name, system, prefix in DEMO_SCHOOLS:
            self.stdout.write(
                f"  {name} ({School.System(system).label}): {prefix}admin, "
                f"{prefix}teacher1, {prefix}teacher2, {prefix}student1..5, {prefix}parent1"
            )
        self.stdout.write("  Django admin only: platform")


@transaction.atomic
def build_school(slug, name, system, prefix):
    school, _ = onboard_school(
        name=name,
        system=system,
        admin={
            "username": f"{prefix}admin",
            "email": f"{prefix}admin@yap.school",
            "password": PASSWORD,
            "first_name": "Ngozi",
            "last_name": "Eze",
        },
    )
    if school.slug != slug:  # onboarding derives the slug from the name; pin it for re-runs
        school.slug = slug
        school.save(update_fields=["slug"])

    session = create_session(school, "2025/2026", make_current=True)
    term = session.terms.get(is_current=True)

    def user(username, role, first, last):
        return User.objects.create_user(
            username=f"{prefix}{username}",
            email=f"{prefix}{username}@yap.school",
            password=PASSWORD,
            role=role,
            first_name=first,
            last_name=last,
            school=school,
        )

    teacher1 = user("teacher1", User.Role.TEACHER, "Ada", "Obi")
    teacher2 = user("teacher2", User.Role.TEACHER, "Bode", "Ade")
    students = [user(f"student{i}", User.Role.STUDENT, "Kid", str(i)) for i in range(1, 6)]
    parent1 = user("parent1", User.Role.PARENT, "Chidi", "Okafor")
    Guardianship.objects.create(parent=parent1, student=students[0], relationship="Father")

    first_level = school.levels.order_by("order").first()
    class_a = Classroom.objects.create(
        school=school, level=first_level, arm="A", form_teacher=teacher1
    )
    class_b = Classroom.objects.create(
        school=school, level=first_level, arm="B", form_teacher=teacher2
    )
    maths, english, science = (
        Subject.objects.create(school=school, name=n) for n in ("Mathematics", "English", "Science")
    )
    for teacher, classroom, subject in [
        (teacher1, class_a, maths),
        (teacher1, class_b, maths),
        (teacher1, class_a, english),
        (teacher2, class_b, english),
        (teacher2, class_a, science),
        (teacher2, class_b, science),
    ]:
        TeachingAssignment.objects.create(
            session=session, classroom=classroom, subject=subject, teacher=teacher
        )
    for student in students[:3]:
        Enrollment.objects.create(session=session, classroom=class_a, student=student)
    for student in students[3:]:
        Enrollment.objects.create(session=session, classroom=class_b, student=student)

    def lesson(title, classroom, subject, teacher, content):
        return Lesson.objects.create(
            title=title,
            content=content,
            classroom=classroom,
            subject=subject,
            term=term,
            created_by=teacher,
        )

    fractions = lesson("Fractions", class_a, maths, teacher1, "Half of a half is a quarter.")
    tenses = lesson("Past Tenses", class_a, english, teacher1, "Was, were, had.")
    lesson("Photosynthesis", class_b, science, teacher2, "How plants make food.")
    lesson("Chemical Reactions", class_b, science, teacher2, "Reactions change substances.")
    Completion.objects.create(lesson=fractions, student=students[0])
    Completion.objects.create(lesson=tenses, student=students[0])

    now = timezone.now()
    quiz = Assessment.objects.create(
        title="Algebra Basics Quiz",
        type=Assessment.Type.QUIZ,
        classroom=class_a,
        subject=maths,
        term=term,
        created_by=teacher1,
        due_at=now + timedelta(days=3),
        max_points=5,
    )
    picks = []  # shortcut: student1 answers 2 of 3 correctly (4 of 5 points)
    for text, points, right, wrong, picks_right in [
        ("2 + 2 * 2 = ?", 2, "6", "8", True),
        ("Solve: x - 5 = 0", 1, "x = 5", "x = -5", True),
        ("3^2 = ?", 2, "9", "6", False),
    ]:
        question = Question.objects.create(assessment=quiz, text=text, points=points)
        correct = Choice.objects.create(question=question, text=right, is_correct=True)
        incorrect = Choice.objects.create(question=question, text=wrong, is_correct=False)
        picks.append((question, correct if picks_right else incorrect))
    submission = Submission.objects.create(
        assessment=quiz,
        student=students[0],
        score=sum(q.points for q, c in picks if c.is_correct),
        graded_at=now,
    )
    Answer.objects.bulk_create(
        Answer(submission=submission, question=q, choice=c) for q, c in picks
    )

    essay = Assessment.objects.create(
        title="Essay: Science in Daily Life",
        type=Assessment.Type.ASSIGNMENT,
        classroom=class_a,
        subject=science,
        term=term,
        created_by=teacher2,
        max_points=10,
        due_at=now + timedelta(days=7),
    )
    Submission.objects.create(
        assessment=essay,
        student=students[1],
        text="Science is everywhere, from cooking to phones.",
        score=7,
        graded_at=now,
    )

    # term scores for class A (not published, so the admin can try publishing): each student
    # gets a share of every component's maximum, so totals differ and positions are visible
    components = list(school.components.order_by("order"))
    share = {
        (maths, 0): 0.9,
        (maths, 1): 0.7,
        (maths, 2): 0.45,
        (english, 0): 0.8,
        (english, 1): 0.75,
        (english, 2): 0.6,
    }
    Score.objects.bulk_create(
        Score(
            student=student,
            subject=subject,
            term=term,
            component=component,
            value=round(component.max_score * share[(subject, i)], 2),
            entered_by=teacher1,
        )
        for i, student in enumerate(students[:3])
        for subject in (maths, english)
        for component in components
    )
    TermResult.objects.create(
        student=students[0],
        term=term,
        classroom=class_a,
        form_teacher_comment="A hardworking and attentive student.",
    )

    LiveClass.objects.create(
        title="Algebra Revision Session",
        classroom=class_a,
        subject=maths,
        term=term,
        hosted_by=teacher1,
        starts_at=now + timedelta(days=1),
        ends_at=now + timedelta(days=1, hours=1),
        join_url=f"https://meet.jit.si/yap-{slug}-algebra-revision",
    )
