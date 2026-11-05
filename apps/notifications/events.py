"""The events people are notified about, and who hears of each.

- A term's results are published: each student with a report card, and their parents.
- A student is marked absent (today's or yesterday's register): their parents.
- A quiz or assignment is set: the students of the class.
- A live class starts within 15 minutes: the students of the class (see ``live_class_reminders``,
  run every minute by the scheduler).
"""

from collections import defaultdict
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from apps.accounts.models import Guardianship, User

from .models import Notification
from .services import notify

Kind = Notification.Kind
REMIND_BEFORE = timedelta(minutes=15)
ABSENCE_ALERT_DAYS = 1  # registers filled in later than yesterday don't alert parents


def _parents_of(students):
    by_student = defaultdict(list)
    links = Guardianship.objects.filter(student__in=students).select_related("parent")
    for link in links:
        if link.parent.is_active:
            by_student[link.student_id].append(link.parent)
    return by_student


def _students_in(classroom, session):
    return list(
        User.objects.filter(
            enrollments__classroom=classroom, enrollments__session=session, is_active=True
        )
    )


def _when(school, moment, with_date=True):
    local = school.local(moment)
    return local.strftime("%a %-d %b, %H:%M" if with_date else "%H:%M")


def results_published(term):
    from apps.results.models import TermResult

    school = term.session.school
    students = [
        result.student
        for result in TermResult.objects.filter(term=term, student__is_active=True)
        .select_related("student")
        .order_by("pk")
    ]
    parents = _parents_of(students)
    data_for = lambda student: {"term": term.pk, "student": student.pk}  # noqa: E731
    messages = []
    for student in students:
        messages.append(
            (
                student,
                f"Your {term.name} report card is ready",
                f"Your report card for {term} is published. Open YAP to see it.",
                data_for(student),
            )
        )
        name = student.display_name
        for parent in parents[student.pk]:
            messages.append(
                (
                    parent,
                    f"{name}'s {term.name} report card is ready",
                    f"{name}'s report card for {term} is published. Open YAP to see it.",
                    data_for(student),
                )
            )
    return notify(Kind.RESULTS_PUBLISHED, school, messages)


def marked_absent(classroom, date, students):
    school = classroom.school
    if (school.today() - date).days > ABSENCE_ALERT_DAYS or not students:
        return []
    parents = _parents_of(students)
    day = date.strftime("%A %-d %B")
    messages = [
        (
            parent,
            f"{student.display_name} was marked absent",
            f"{student.display_name} was marked absent from {classroom.name} on {day}. "
            "If you think this is a mistake, contact the school.",
            {"student": student.pk, "date": date.isoformat(), "classroom": classroom.pk},
        )
        for student in students
        for parent in parents[student.pk]
    ]
    return notify(Kind.ABSENT, school, messages)


def work_set(assessment):
    school = assessment.classroom.school
    kind = assessment.get_type_display().lower()
    title = f"New {kind} in {assessment.subject.name}: {assessment.title}"
    due = f" It is due {_when(school, assessment.due_at)}." if assessment.due_at else ""
    body = f"A new {kind}, {assessment.title}, was set for {assessment.classroom.name}.{due}"
    students = _students_in(assessment.classroom, assessment.term.session)
    data = {"assessment": assessment.pk}
    return notify(Kind.WORK_SET, school, [(s, title, body, data) for s in students])


def live_class_reminders():
    """Every minute: remind students of live classes starting in the next 15 minutes. Each
    class is reminded once (``reminded_at``); moving it to a new time reminds again."""
    from apps.live_classes.models import LiveClass

    now = timezone.now()
    with transaction.atomic():
        due = list(
            LiveClass.objects.select_for_update(skip_locked=True, of=("self",))
            .filter(reminded_at__isnull=True, starts_at__gt=now, starts_at__lte=now + REMIND_BEFORE)
            .select_related("classroom__school", "subject", "term__session", "hosted_by")
        )
        LiveClass.objects.filter(pk__in=[c.pk for c in due]).update(reminded_at=now)
        for live in due:
            school = live.classroom.school
            at = _when(school, live.starts_at, with_date=False)
            host = f" with {live.hosted_by.display_name}" if live.hosted_by else ""
            notify(
                Kind.LIVE_CLASS_SOON,
                school,
                [
                    (
                        student,
                        f"Live class at {at}: {live.title}",
                        f"{live.subject.name}{host} starts at {at}. Open YAP to join.",
                        {"live_class": live.pk},
                    )
                    for student in _students_in(live.classroom, live.term.session)
                ],
            )
    return len(due)
