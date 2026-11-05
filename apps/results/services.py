"""Turning scores into results.

``compute_class_results`` is the single source of truth: draft previews call it directly and
publishing stores its output. Rules:

- a subject's total is the sum of its component scores (a missing component counts as 0);
  subjects a student has no scores in at all are left off their report card
- grade = the band with the highest minimum the total reaches
- a student's average = total of subject totals / number of subjects
- positions use competition ranking (1, 2, 2, 4) and only exist if the school shows them;
  GPA is the mean grade point and only exists if the school uses GPA
"""

from collections import defaultdict
from decimal import ROUND_HALF_UP, Decimal

from django.db import transaction
from django.utils import timezone

from apps.academics.models import Enrollment, Term
from apps.accounts.models import User
from apps.attendance.services import class_attendance, report_card_attendance

from .models import Publication, Score, SubjectResult, TermResult

TWO_PLACES = Decimal("0.01")


def money(value):
    """Round to two decimal places, halves up (what a teacher would do by hand)."""
    return Decimal(value).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


def competition_rank(values):
    """{key: value} -> {key: rank}, highest value first; ties share a rank (1, 2, 2, 4)."""
    ordered = sorted(values.values(), reverse=True)
    return {key: 1 + sum(1 for v in ordered if v > value) for key, value in values.items()}


def grade_for(total, bands):
    """``bands`` sorted by min_score descending; the scale always has a band starting at 0."""
    for band in bands:
        if total >= band.min_score:
            return band
    return bands[-1]


def class_students(classroom, session):
    return list(
        User.objects.filter(
            enrollments__classroom=classroom, enrollments__session=session
        ).order_by("last_name", "first_name", "username")
    )


def compute_class_results(classroom, term):
    """Results for every student of ``classroom`` in ``term``, computed from current scores.

    Returns {"students": [{"student", "subjects": [...], "summary": {...}}], "components",
    "subject_stats"}. Numbers are Decimals.
    """
    school = classroom.school
    students = class_students(classroom, term.session)
    components = list(school.score_split(term.session))
    bands = list(school.grade_bands.order_by("-min_score"))

    # scores[student_id][subject] = {component_id: value}
    scores = defaultdict(lambda: defaultdict(dict))
    subjects = {}
    for score in Score.objects.filter(term=term, student__in=students).select_related("subject"):
        scores[score.student_id][score.subject_id][score.component_id] = score.value
        subjects[score.subject_id] = score.subject

    # subject totals per student, then class statistics per subject
    totals = defaultdict(dict)  # subject_id -> {student_id: total}
    for student_id, by_subject in scores.items():
        for subject_id, values in by_subject.items():
            totals[subject_id][student_id] = money(sum(values.values(), Decimal(0)))
    subject_stats = {}
    for subject_id, by_student in totals.items():
        values = list(by_student.values())
        subject_stats[subject_id] = {
            "average": money(sum(values) / len(values)),
            "highest": max(values),
            "lowest": min(values),
            "positions": competition_rank(by_student) if school.show_position else {},
        }

    rows = []
    for student in students:
        lines = []
        for subject_id in sorted(scores[student.pk], key=lambda sid: subjects[sid].name):
            total = totals[subject_id][student.pk]
            band = grade_for(total, bands)
            stats = subject_stats[subject_id]
            lines.append(
                {
                    "subject": subjects[subject_id],
                    "scores": [
                        {
                            "component": c.name,
                            "max_score": c.max_score,
                            "value": scores[student.pk][subject_id].get(c.pk),
                        }
                        for c in components
                    ],
                    "total": total,
                    "grade": band.label,
                    "remark": band.remark,
                    "grade_point": band.grade_point,
                    "class_average": stats["average"],
                    "class_highest": stats["highest"],
                    "class_lowest": stats["lowest"],
                    "position": stats["positions"].get(student.pk),
                }
            )
        grand_total = money(sum((line["total"] for line in lines), Decimal(0)))
        points = [line["grade_point"] for line in lines]
        rows.append(
            {
                "student": student,
                "subjects": lines,
                "summary": {
                    "total": grand_total,
                    "subjects_count": len(lines),
                    "average": money(grand_total / len(lines)) if lines else None,
                    "gpa": (
                        money(sum(points) / len(points))
                        if school.use_gpa and points and None not in points
                        else None
                    ),
                    "position": None,
                    "out_of": None,
                },
            }
        )

    if school.show_position:
        ranked = {
            row["student"].pk: row["summary"]["average"]
            for row in rows
            if row["summary"]["average"] is not None
        }
        positions = competition_rank(ranked)
        for row in rows:
            row["summary"]["position"] = positions.get(row["student"].pk)
            row["summary"]["out_of"] = len(ranked) if row["student"].pk in ranked else None

    return {"students": rows, "components": components, "subject_stats": subject_stats}


def classrooms_in_session(school, session):
    return (
        school.classrooms.filter(enrollments__session=session)
        .select_related("school", "form_teacher")
        .distinct()
    )


# the computed fields of a TermResult, (re)written at publish time
PUBLISHED_FIELDS = [
    "classroom",
    "total",
    "average",
    "subjects_count",
    "position",
    "out_of",
    "gpa",
    "form_teacher_name",
    "attendance",
    "updated_at",
]


@transaction.atomic
def publish_term(term, user):
    """Snapshot every class's results for ``term`` and lock its scores.

    Writes in bulk per class, so publishing costs a handful of queries per class rather than
    several per student.
    """
    school = term.session.school
    now = timezone.now()
    for classroom in classrooms_in_session(school, term.session):
        form_teacher = classroom.form_teacher.display_name if classroom.form_teacher else ""
        rows = compute_class_results(classroom, term)["students"]
        if not rows:
            continue
        students = [row["student"] for row in rows]
        attendance = class_attendance(classroom, term, students)
        # comments written before publishing live on existing TermResults: keep those rows
        existing = {
            r.student_id: r for r in TermResult.objects.filter(term=term, student__in=students)
        }

        results = []
        for row in rows:
            summary = row["summary"]
            result = existing.get(row["student"].pk) or TermResult(
                student=row["student"], term=term
            )
            result.classroom = classroom
            result.total = summary["total"]
            result.average = summary["average"]
            result.subjects_count = summary["subjects_count"]
            result.position = summary["position"]
            result.out_of = summary["out_of"]
            result.gpa = summary["gpa"]
            result.form_teacher_name = form_teacher
            result.attendance = report_card_attendance(attendance[row["student"].pk])
            result.updated_at = now
            results.append(result)
        TermResult.objects.bulk_update([r for r in results if r.pk], PUBLISHED_FIELDS)
        TermResult.objects.bulk_create([r for r in results if not r.pk])

        SubjectResult.objects.filter(term_result__in=results).delete()
        SubjectResult.objects.bulk_create(
            SubjectResult(
                term_result=result,
                subject=line["subject"],
                subject_name=line["subject"].name,
                scores=[
                    {**s, "value": str(s["value"]) if s["value"] is not None else None}
                    for s in line["scores"]
                ],
                total=line["total"],
                grade=line["grade"],
                remark=line["remark"],
                grade_point=line["grade_point"],
                class_average=line["class_average"],
                class_highest=line["class_highest"],
                class_lowest=line["class_lowest"],
                position=line["position"],
            )
            for result, row in zip(results, rows, strict=True)
            for line in row["subjects"]
        )
    return Publication.objects.create(
        term=term,
        published_by=user,
        grading_scale=grading_scale(school),
        show_position=school.show_position,
        use_gpa=school.use_gpa,
    )


def dec(value):
    """Decimal -> string for JSON (like DRF's DecimalField), keeping None."""
    return None if value is None else str(value)


def grading_scale(school):
    return [
        {
            "label": band.label,
            "min_score": dec(band.min_score),
            "remark": band.remark,
            "grade_point": dec(band.grade_point),
        }
        for band in school.grade_bands.order_by("-min_score")
    ]


@transaction.atomic
def unpublish_term(term):
    """Reopen a term for corrections: hide report cards, unlock scores and attendance, keep
    comments."""
    Publication.objects.filter(term=term).delete()
    results = TermResult.objects.filter(term=term)
    SubjectResult.objects.filter(term_result__in=results).delete()
    results.update(
        total=None,
        average=None,
        subjects_count=0,
        position=None,
        out_of=None,
        gpa=None,
        attendance=None,
    )


def lock_term(term):
    """Row-lock the term for the rest of the transaction.

    Every write that depends on whether the term is published (scores, comments, publish,
    unpublish) takes this lock first and only then checks, so a score can't slip in while
    the term is being published, and two admins can't publish the same term at once.
    """
    Term.objects.select_for_update().get(pk=term.pk)


def is_published(term):
    return Publication.objects.filter(term=term).exists()


def enrollment_for(student, session):
    return (
        Enrollment.objects.select_related("classroom__level", "classroom__school")
        .filter(student=student, session=session)
        .first()
    )
