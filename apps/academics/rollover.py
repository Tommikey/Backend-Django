"""Moving a school from one session to the next: who goes into which class, and who teaches what.

Each student enrolled in the old session gets an action:

    promote   the same arm one level up (JSS1A -> JSS2A); if that level has a single class,
              that class. Students in the final level graduate instead.
    repeat    the same class again
    move      any class the admin names
    graduate  finished school: not enrolled in the new session
    leave     left the school: not enrolled in the new session

The admin's decisions override the defaults. Graduates and leavers keep their accounts, so they
can still read their report cards; deactivate them separately if wanted.

The plan is computed in full before anything is written; a student who can't be placed is an
error and blocks committing. Committing records each student's outcome on their old enrollment
(promoted, graduated, left...). A later run skips students who already have an outcome or a
class in the new session, unless the admin sends a decision for them (say, a returning leaver),
so running it again is safe. Queries don't grow with the number of students.
"""

from dataclasses import dataclass, field

from django.db import transaction

from apps.accounts.refs import student_ref
from apps.results.models import Publication, TermResult
from apps.results.services import dec

from .models import Enrollment, TeachingAssignment
from .services import make_term_current

PROMOTE, REPEAT, MOVE, GRADUATE, LEAVE = "promote", "repeat", "move", "graduate", "leave"
ACTIONS = [PROMOTE, REPEAT, MOVE, GRADUATE, LEAVE]
OUTCOMES = {
    PROMOTE: Enrollment.Outcome.PROMOTED,
    REPEAT: Enrollment.Outcome.REPEATED,
    MOVE: Enrollment.Outcome.MOVED,
    GRADUATE: Enrollment.Outcome.GRADUATED,
    LEAVE: Enrollment.Outcome.LEFT,
}
STAYS = {PROMOTE, REPEAT, MOVE}  # actions that enroll the student in the new session


@dataclass
class Placement:
    enrollment: object  # the old session's
    student: object
    from_classroom: object
    action: str = PROMOTE
    to_classroom: object = None
    latest_average: object = None
    note: str = ""
    error: str = ""


@dataclass
class Plan:
    placements: list = field(default_factory=list)
    already_done: list = field(default_factory=list)  # handled by an earlier run
    unpublished_terms: list = field(default_factory=list)
    teaching_to_copy: list = field(default_factory=list)

    @property
    def valid(self):
        return not any(p.error for p in self.placements)


def _next_classes(school):
    """{classroom_id: the default class one level up, or None if it's the final level}, plus
    {classroom_id: why there is no default} for ambiguous cases."""
    levels = list(school.levels.order_by("order"))
    classes = list(school.classrooms.select_related("level"))
    by_level = {}
    for c in classes:
        by_level.setdefault(c.level_id, []).append(c)
    following = {levels[i].pk: levels[i + 1] for i in range(len(levels) - 1)}

    targets, problems = {}, {}
    for c in classes:
        nxt = following.get(c.level_id)
        if nxt is None:
            targets[c.pk] = None  # final level: graduates
            continue
        options = by_level.get(nxt.pk, [])
        same_arm = [o for o in options if o.arm.lower() == c.arm.lower()]
        if same_arm:
            targets[c.pk] = same_arm[0]
        elif len(options) == 1:
            targets[c.pk] = options[0]
        elif not options:
            problems[c.pk] = f"{nxt.name} has no classes yet; create one or choose a class."
        else:
            problems[c.pk] = f"{nxt.name} has no arm {c.arm or '(none)'}; choose a class."
    return targets, problems


def plan_rollover(school, from_session, to_session, decisions, copy_teaching):
    """``decisions``: {student_id: {"action": ..., "classroom": Classroom or None}}."""
    enrollments = list(
        Enrollment.objects.filter(session=from_session)
        .select_related("student", "classroom__level")
        .order_by(
            "classroom__level__order", "classroom__arm", "student__last_name", "student__first_name"
        )
    )
    already = set(
        Enrollment.objects.filter(session=to_session).values_list("student_id", flat=True)
    )
    averages = {}
    for result in (
        TermResult.objects.filter(term__session=from_session, term__publication__isnull=False)
        .order_by("term__order")
        .only("student_id", "average")
    ):
        averages[result.student_id] = result.average  # the latest published term wins
    targets, problems = _next_classes(school)

    plan = Plan(
        unpublished_terms=list(
            from_session.terms.exclude(
                pk__in=Publication.objects.filter(term__session=from_session).values("term")
            ).order_by("order")
        )
    )
    for enrollment in enrollments:
        student, current = enrollment.student, enrollment.classroom
        decision = decisions.get(student.pk, {})
        # an earlier run placed them, or recorded that they graduated or left; only an
        # explicit decision reopens someone who isn't in a class next session
        if student.pk in already or (enrollment.outcome and not decision):
            plan.already_done.append(student)
            continue
        p = Placement(enrollment, student, current, latest_average=averages.get(student.pk))
        chosen = decision.get("classroom")
        final_level = current.pk in targets and targets[current.pk] is None
        p.action = decision.get("action") or (GRADUATE if final_level else PROMOTE)

        if p.action in (GRADUATE, LEAVE):
            pass
        elif chosen is not None:
            p.to_classroom = chosen
        elif p.action == REPEAT:
            p.to_classroom = current
        elif p.action == MOVE:
            p.error = "Say which class to move them to."
        elif current.pk in problems:
            p.error = problems[current.pk]
        elif final_level:
            p.error = f"{current.name} is the final level; graduate them or choose a class."
        else:
            p.to_classroom = targets[current.pk]
        if p.action in STAYS and p.to_classroom is not None and p.to_classroom == current:
            p.note = "Same class as this session."
        plan.placements.append(p)

    if copy_teaching:
        existing = set(
            TeachingAssignment.objects.filter(session=to_session).values_list(
                "classroom_id", "subject_id"
            )
        )
        plan.teaching_to_copy = [
            a
            for a in TeachingAssignment.objects.filter(session=from_session)
            if (a.classroom_id, a.subject_id) not in existing
        ]
    return plan


@transaction.atomic
def apply_rollover(plan, to_session, make_current):
    for p in plan.placements:
        p.enrollment.outcome = OUTCOMES[p.action]
    Enrollment.objects.bulk_update([p.enrollment for p in plan.placements], ["outcome"])
    Enrollment.objects.bulk_create(
        Enrollment(session=to_session, classroom=p.to_classroom, student=p.student)
        for p in plan.placements
        if p.action in STAYS
    )
    copies = TeachingAssignment.objects.bulk_create(
        TeachingAssignment(
            session=to_session,
            classroom_id=a.classroom_id,
            subject_id=a.subject_id,
            teacher_id=a.teacher_id,
        )
        for a in plan.teaching_to_copy
    )
    _copy_timetable(plan.teaching_to_copy, copies, to_session)
    if make_current:
        make_term_current(to_session.terms.order_by("order").first())


def _copy_timetable(old_assignments, new_assignments, to_session):
    """The copied assignments keep their places on the timetable in the new session."""
    from apps.timetable.models import Slot

    new_for = dict(zip((a.pk for a in old_assignments), new_assignments, strict=True))
    Slot.objects.bulk_create(
        Slot(
            assignment=new_for[slot.assignment_id],
            session=to_session,
            classroom_id=slot.classroom_id,
            day=slot.day,
            period_id=slot.period_id,
        )
        for slot in Slot.objects.filter(assignment__in=list(new_for))
    )


def report(plan, from_session, to_session, committed):
    counts = {action: 0 for action in ACTIONS}
    for p in plan.placements:
        counts[p.action] += 1

    def ref(classroom):
        return {"id": classroom.pk, "name": classroom.name} if classroom else None

    return {
        "from_session": {"id": from_session.pk, "name": from_session.name},
        "to_session": {"id": to_session.pk, "name": to_session.name},
        "committed": committed,
        "valid": plan.valid,
        "summary": {
            "promoted": counts[PROMOTE],
            "repeating": counts[REPEAT],
            "moved": counts[MOVE],
            "graduating": counts[GRADUATE],
            "leaving": counts[LEAVE],
            "already_done": len(plan.already_done),
            "teaching_assignments_copied": len(plan.teaching_to_copy),
        },
        "unpublished_terms": [
            {"id": t.pk, "name": t.name, "session": from_session.name}
            for t in plan.unpublished_terms
        ],
        "students": [
            {
                "student": student_ref(p.student),
                "from_classroom": ref(p.from_classroom),
                "action": p.action,
                "to_classroom": ref(p.to_classroom),
                "latest_average": dec(p.latest_average),
                "note": p.note,
                "error": p.error,
            }
            for p in plan.placements
        ],
    }
