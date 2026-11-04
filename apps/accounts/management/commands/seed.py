from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.academics.models import Classroom, Completion, Enrollment, Lesson, Subject
from apps.accounts.models import Guardianship, User
from apps.assessments.models import Assessment, Choice, Question, Submission
from apps.schools.models import School
from apps.schools.services import onboard_school
from apps.sessions.models import StudySession

PASSWORD = "pass1234"


class Command(BaseCommand):
    help = "Create demo data for local development. Safe to re-run."

    def handle(self, *args, **options):
        # platform staff: Django admin only, belongs to no school
        platform, _ = User.objects.get_or_create(
            username="platform",
            defaults={"email": "platform@yap.school", "is_staff": True, "is_superuser": True},
        )
        platform.set_password(PASSWORD)
        platform.save()

        school = School.objects.filter(slug="demo-secondary-school").first()
        if school is None:
            school, _ = onboard_school(
                name="Demo Secondary School",
                system=School.System.NG,
                admin={
                    "username": "admin",
                    "email": "admin@yap.school",
                    "password": PASSWORD,
                    "first_name": "Ngozi",
                    "last_name": "Eze",
                },
            )

        def user(username, role, first, last):
            u, created = User.objects.get_or_create(
                username=username,
                defaults={
                    "email": f"{username}@yap.school",
                    "role": role,
                    "first_name": first,
                    "last_name": last,
                    "school": school,
                },
            )
            if created:
                u.set_password(PASSWORD)
                u.save(update_fields=["password"])
            return u

        teacher1 = user("teacher1", User.Role.TEACHER, "Ada", "Obi")
        teacher2 = user("teacher2", User.Role.TEACHER, "Bode", "Ade")
        students = [user(f"student{i}", User.Role.STUDENT, "Kid", str(i)) for i in range(1, 6)]
        parent1 = user("parent1", User.Role.PARENT, "Chidi", "Okafor")
        Guardianship.objects.get_or_create(
            parent=parent1, student=students[0], defaults={"relationship": "Father"}
        )

        def subject(name):
            s, _ = Subject.objects.get_or_create(school=school, name=name)
            return s

        math, english, science = subject("Mathematics"), subject("English"), subject("Science")

        def classroom(name, created_by):
            c, _ = Classroom.objects.get_or_create(
                school=school, name=name, defaults={"created_by": created_by}
            )
            return c

        grade8a = classroom("Grade 8A", teacher1)
        grade8b = classroom("Grade 8B", teacher2)

        for student in students[:3]:
            Enrollment.objects.get_or_create(classroom=grade8a, student=student)
        for student in students[3:]:
            Enrollment.objects.get_or_create(classroom=grade8b, student=student)

        def lesson(title, classroom_, subject_, teacher, content=""):
            obj, _ = Lesson.objects.get_or_create(
                title=title,
                defaults={
                    "classroom": classroom_,
                    "subject": subject_,
                    "created_by": teacher,
                    "content": content,
                },
            )
            return obj

        fractions = lesson("Fractions", grade8a, math, teacher1, "Half of a half is a quarter.")
        tenses = lesson("Past Tenses", grade8a, english, teacher1, "Was, were, had.")
        lesson("Photosynthesis", grade8b, science, teacher2, "How plants make food.")
        lesson("Chemical Reactions", grade8b, science, teacher2, "Reactions change substances.")

        Completion.objects.get_or_create(lesson=fractions, student=students[0])
        Completion.objects.get_or_create(lesson=tenses, student=students[0])

        quiz, created = Assessment.objects.get_or_create(
            title="Algebra Basics Quiz",
            defaults={
                "type": Assessment.Type.QUIZ,
                "classroom": grade8a,
                "subject": math,
                "created_by": teacher1,
                "due_at": timezone.now() + timedelta(days=3),
            },
        )
        if created:
            q1 = Question.objects.create(assessment=quiz, text="2 + 2 * 2 = ?", points=2)
            Choice.objects.create(question=q1, text="6", is_correct=True)
            Choice.objects.create(question=q1, text="8", is_correct=False)
            q2 = Question.objects.create(assessment=quiz, text="Solve: x - 5 = 0", points=1)
            Choice.objects.create(question=q2, text="x = 5", is_correct=True)
            Choice.objects.create(question=q2, text="x = -5", is_correct=False)
            q3 = Question.objects.create(assessment=quiz, text="3^2 = ?", points=2)
            Choice.objects.create(question=q3, text="9", is_correct=True)
            Choice.objects.create(question=q3, text="6", is_correct=False)
            quiz.max_points = 5
            quiz.save(update_fields=["max_points"])

        if not Submission.objects.filter(assessment=quiz, student=students[0]).exists():
            from apps.assessments.models import Answer

            q1, q2, q3 = quiz.questions.order_by("id")
            # shortcut: hardcoded picks, student1 answers 2 of 3 correctly (4/5 pts)
            picks = [
                (q1, q1.choices.get(is_correct=True)),
                (q2, q2.choices.get(is_correct=True)),
                (q3, q3.choices.get(is_correct=False)),
            ]
            submission = Submission.objects.create(assessment=quiz, student=students[0])
            Answer.objects.bulk_create(
                [Answer(submission=submission, question=q, choice=c) for q, c in picks]
            )
            submission.score = sum(q.points for q, c in picks if c.is_correct)
            submission.graded_at = timezone.now()
            submission.save(update_fields=["score", "graded_at"])

        assignment, _ = Assessment.objects.get_or_create(
            title="Essay: Science in Daily Life",
            defaults={
                "type": Assessment.Type.ASSIGNMENT,
                "classroom": grade8a,
                "subject": science,
                "created_by": teacher1,
                "max_points": 10,
                "due_at": timezone.now() + timedelta(days=7),
            },
        )
        sub, created = Submission.objects.get_or_create(
            assessment=assignment,
            student=students[1],
            defaults={"text": "Science is everywhere, from cooking to phones."},
        )
        if created:
            sub.score = 7
            sub.graded_at = timezone.now()
            sub.save(update_fields=["score", "graded_at"])

        StudySession.objects.get_or_create(
            title="Algebra Revision Session",
            defaults={
                "classroom": grade8a,
                "subject": math,
                "hosted_by": teacher1,
                "starts_at": timezone.now() + timedelta(days=1),
                "ends_at": timezone.now() + timedelta(days=1, hours=1),
                "join_url": "https://meet.jit.si/yap-algebra-revision",
            },
        )

        self.stdout.write(self.style.SUCCESS("Seed complete. Logins (password pass1234):"))
        self.stdout.write("  school admin: admin   teachers: teacher1, teacher2")
        self.stdout.write("  students: student1..student5   parent: parent1 (of student1)")
        self.stdout.write("  platform (Django admin only): platform")
