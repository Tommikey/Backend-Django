"""What each role should see first, built from the other apps' data.

Every block has a fixed number of queries (a parent's costs a few per child). Lists are short:
the dashboard points at work, the list endpoints hold the rest.
"""

from django.db.models import Count, Exists, OuterRef, Q
from django.utils import timezone

from apps.academics.models import Classroom, Enrollment
from apps.academics.rules import enrolled_exists, teaching_exists
from apps.accounts.models import User
from apps.assessments.models import Assessment, Submission
from apps.attendance.models import AttendanceRecord
from apps.attendance.services import class_attendance, report_card_attendance
from apps.live_classes.models import LiveClass
from apps.results.models import Publication, Score, TermResult
from apps.results.services import dec

LIST_LIMIT = 5


def ref(obj):
    return {"id": obj.pk, "name": obj.name}


def term_ref(term):
    return {"id": term.pk, "name": term.name, "session": term.session.name}


def live_class_item(live):
    return {
        "id": live.pk,
        "title": live.title,
        "classroom": ref(live.classroom),
        "subject": ref(live.subject),
        "starts_at": live.starts_at,
        "ends_at": live.ends_at,
        "join_url": live.join_url,
    }


def upcoming_live_classes(condition):
    return [
        live_class_item(live)
        for live in LiveClass.objects.filter(condition, starts_at__gte=timezone.now())
        .select_related("classroom__level", "subject")
        .order_by("starts_at")[:LIST_LIMIT]
    ]


def latest_report_card(student):
    result = (
        TermResult.objects.filter(student=student, term__publication__isnull=False)
        .select_related("term__session", "term__publication")
        .order_by("-term__publication__published_at")
        .first()
    )
    if result is None:
        return None
    return {
        "term": term_ref(result.term),
        "published_at": result.term.publication.published_at,
        "average": dec(result.average),
        "position": result.position,
        "out_of": result.out_of,
        "gpa": dec(result.gpa),
    }


def student_work(student, term):
    """A student's unsubmitted work this term: the next few items (soonest first), how many
    are open, and how many are overdue."""
    if term is None:
        return [], 0, 0
    open_work = (
        Assessment.objects.filter(enrolled_exists(student), term=term)
        .exclude(submissions__student=student)
        .select_related("subject")
    )
    now = timezone.now()
    due = open_work.filter(Q(due_at__gte=now) | Q(due_at__isnull=True)).order_by(
        "due_at", "-created_at"
    )  # dated work first (Postgres sorts NULLs last ascending)
    items = [
        {
            "id": a.pk,
            "title": a.title,
            "type": a.type,
            "subject": ref(a.subject),
            "due_at": a.due_at,
        }
        for a in due[:LIST_LIMIT]
    ]
    return items, due.count(), open_work.filter(due_at__lt=now).count()


def student_attendance(student, term):
    if term is None:
        return None
    enrollment = (
        Enrollment.objects.filter(student=student, session_id=term.session_id)
        .select_related("classroom")
        .first()
    )
    if enrollment is None:
        return None
    summary = class_attendance(enrollment.classroom, term, [student])[student.pk]
    return report_card_attendance(summary)


def student_block(student, term):
    due, due_count, overdue = student_work(student, term)
    return {
        "due_work": due,
        "due_count": due_count,
        "overdue_count": overdue,
        "upcoming_live_classes": upcoming_live_classes(enrolled_exists(student)),
        "attendance": student_attendance(student, term),
        "latest_report_card": latest_report_card(student),
    }


def parent_block(parent, term):
    links = list(parent.children_links.select_related("student").order_by("student__first_name"))
    classes = {}
    if term is not None:
        classes = {
            e.student_id: ref(e.classroom)
            for e in Enrollment.objects.filter(
                session_id=term.session_id, student__in=[link.student_id for link in links]
            ).select_related("classroom__level")
        }
    children = []
    for link in links:
        child = link.student
        _, due_count, overdue = student_work(child, term)
        children.append(
            {
                "student": {"id": child.pk, "name": child.display_name},
                "classroom": classes.get(child.pk),
                "due_count": due_count,
                "overdue_count": overdue,
                "attendance": student_attendance(child, term),
                "latest_report_card": latest_report_card(child),
            }
        )
    return {"children": children}


def taken_today(today):
    return Exists(AttendanceRecord.objects.filter(classroom=OuterRef("pk"), date=today))


def teacher_block(teacher, term, today):
    registers = [
        {"classroom": ref(c), "taken_today": c.taken}
        for c in teacher.form_classes.select_related("level").annotate(taken=taken_today(today))
    ]
    ungraded = Q(submissions__score__isnull=True)
    to_grade = (
        Assessment.objects.filter(teaching_exists(teacher))
        .annotate(ungraded=Count("submissions", filter=ungraded))
        .filter(ungraded__gt=0)
        .select_related("classroom__level", "subject")
        .order_by("-ungraded", "due_at")
    )
    return {
        "registers": registers,
        "to_grade_count": Submission.objects.filter(
            teaching_exists(teacher, prefix="assessment__"), score__isnull=True
        ).count(),
        "to_grade": [
            {
                "id": a.pk,
                "title": a.title,
                "classroom": ref(a.classroom),
                "subject": ref(a.subject),
                "ungraded": a.ungraded,
            }
            for a in to_grade[:LIST_LIMIT]
        ],
        "upcoming_live_classes": upcoming_live_classes(
            teaching_exists(teacher) | Q(hosted_by=teacher)
        ),
    }


def admin_block(admin, term, today):
    school_id = admin.school_id
    people = User.objects.filter(school_id=school_id, is_active=True).aggregate(
        students=Count("pk", filter=Q(role=User.Role.STUDENT)),
        teachers=Count("pk", filter=Q(role=User.Role.TEACHER)),
        parents=Count("pk", filter=Q(role=User.Role.PARENT)),
    )
    missing, term_status = [], None
    if term is not None:
        in_session = Classroom.objects.filter(
            school_id=school_id, enrollments__session_id=term.session_id
        ).distinct()
        missing = [
            {
                "classroom": ref(c),
                "form_teacher": c.form_teacher.display_name if c.form_teacher else None,
            }
            for c in in_session.select_related("level", "form_teacher")
            .annotate(taken=taken_today(today))
            .filter(taken=False)
        ]
        term_status = {
            "term": term_ref(term),
            "published": Publication.objects.filter(term=term).exists(),
            "classes": in_session.count(),
            "scores_entered": Score.objects.filter(term=term).count(),
        }
    return {"people": people, "registers_missing_today": missing, "term_status": term_status}
