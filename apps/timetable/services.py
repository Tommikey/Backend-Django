"""Timetable rules and the week grids the API returns."""

from django.db.models import Q

from .models import DAYS, SCHOOL_WEEK, Period, Slot


def teacher_clashes(session, wanted, ignore_classroom=None, ignore_assignment=None):
    """Lessons that would double-book a teacher.

    ``wanted``: (teacher_id, day, period_id) triples. Returns the existing slots (in other
    classes, or other assignments) that put one of those teachers in two places at once.
    """
    if not wanted:
        return []
    match = Q()
    for teacher_id, day, period_id in wanted:
        match |= Q(assignment__teacher_id=teacher_id, day=day, period_id=period_id)
    qs = Slot.objects.filter(match, session=session).select_related(
        "assignment__teacher", "assignment__subject", "classroom", "period"
    )
    if ignore_classroom is not None:
        qs = qs.exclude(classroom=ignore_classroom)
    if ignore_assignment is not None:
        qs = qs.exclude(assignment=ignore_assignment)
    return list(qs)


def describe(slot):
    return (
        f"{slot.assignment.teacher.display_name} already teaches {slot.classroom.name} "
        f"{slot.assignment.subject.name} on {DAYS[slot.day]}, {slot.period.name}."
    )


def week(school, slots, with_classroom=False, with_teacher=True):
    """{"periods": [...], "days": [{"day", "name", "lessons": [one per period or null]}]}."""
    periods = list(Period.objects.filter(school=school))
    by_key = {(s.day, s.period_id): s for s in slots}
    days = sorted(set(SCHOOL_WEEK) | {s.day for s in slots})
    out_days = []
    for day in days:
        lessons = []
        for period in periods:
            slot = by_key.get((day, period.pk))
            lessons.append(lesson(slot, with_classroom, with_teacher) if slot else None)
        out_days.append({"day": day, "name": DAYS[day], "lessons": lessons})
    return {"periods": [period_data(p) for p in periods], "days": out_days}


def period_data(period):
    return {
        "id": period.pk,
        "name": period.name,
        "starts_at": period.starts_at.strftime("%H:%M"),
        "ends_at": period.ends_at.strftime("%H:%M"),
        "is_break": period.is_break,
    }


def lesson(slot, with_classroom=False, with_teacher=True):
    a = slot.assignment
    data = {"slot": slot.pk, "subject": {"id": a.subject_id, "name": a.subject.name}}
    if with_teacher:
        data["teacher"] = {"id": a.teacher_id, "name": a.teacher.display_name}
    if with_classroom:
        data["classroom"] = {"id": slot.classroom_id, "name": slot.classroom.name}
    return data


def slots_for(**filters):
    return Slot.objects.filter(**filters).select_related(
        "assignment__subject", "assignment__teacher", "classroom__level", "period"
    )


def today(school, slots):
    """Today's lessons in order, with times: for dashboards."""
    weekday = school.today().isoweekday()
    return [
        {**period_data(s.period), **lesson(s, with_classroom=True)}
        for s in sorted(slots, key=lambda s: s.period.starts_at)
        if s.day == weekday
    ]
