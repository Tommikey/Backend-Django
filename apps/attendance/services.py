"""Counting attendance for a term.

``class_attendance`` is the single source of truth: the class summary, the student view, draft
report cards and publishing all use it.

- days_open: the days this class's register was taken in the term
- present includes late; absent excludes excused (both are also counted on their own)
- unmarked: days the register was taken but this student wasn't marked
"""

from collections import Counter

from .models import AttendanceRecord

Status = AttendanceRecord.Status


def register_dates(classroom, term):
    return list(
        AttendanceRecord.objects.filter(classroom=classroom, term=term)
        .order_by("date")
        .values_list("date", flat=True)
        .distinct()
    )


def _summary(days_open, counts):
    marked = sum(counts.values())
    return {
        "days_open": days_open,
        "present": counts[Status.PRESENT] + counts[Status.LATE],
        "late": counts[Status.LATE],
        "absent": counts[Status.ABSENT],
        "excused": counts[Status.EXCUSED],
        "unmarked": max(days_open - marked, 0),
    }


def class_attendance(classroom, term, students):
    """{student_id: summary} for ``students`` of ``classroom`` in ``term``.

    Every student gets a summary, even with no marks, so a class register reads complete.
    """
    days_open = len(register_dates(classroom, term))
    counts = {student.pk: Counter() for student in students}
    rows = AttendanceRecord.objects.filter(
        classroom=classroom, term=term, student__in=students
    ).values_list("student_id", "status")
    for student_id, status in rows:
        counts[student_id][status] += 1
    return {student_id: _summary(days_open, c) for student_id, c in counts.items()}


def report_card_attendance(summary):
    """The attendance block printed on a report card; None when no register was ever taken."""
    if not summary or summary["days_open"] == 0:
        return None
    return summary
