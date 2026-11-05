"""Report cards as JSON, in one shape whether read from a published snapshot or previewed
live (draft) from current scores.
"""

from apps.accounts.refs import student_ref
from apps.attendance.services import class_attendance, report_card_attendance

from .models import TermResult
from .services import compute_class_results, dec, grading_scale


def _header(student, classroom, term, published, publication=None):
    school = classroom.school
    return {
        "published": published,
        "published_at": publication.published_at if publication else None,
        "school": {"name": school.name, "system": school.system},
        "student": student_ref(student),
        "classroom": {"id": classroom.pk, "name": classroom.name},
        "session": term.session.name,
        "term": {"id": term.pk, "name": term.name},
    }


def _summary(total, average, subjects_count, position, out_of, gpa):
    return {
        "total": dec(total),
        "average": dec(average),
        "subjects_count": subjects_count,
        "position": position,
        "out_of": out_of,
        "gpa": dec(gpa),
    }


def from_snapshot(result, publication):
    """A published report card, exactly as stored at publish time."""
    card = _header(result.student, result.classroom, result.term, True, publication)
    card.update(
        {
            "form_teacher": result.form_teacher_name,
            "subjects": [
                {
                    "subject": line.subject_name,
                    "scores": line.scores,
                    "total": dec(line.total),
                    "grade": line.grade,
                    "remark": line.remark,
                    "grade_point": dec(line.grade_point),
                    "class_average": dec(line.class_average),
                    "class_highest": dec(line.class_highest),
                    "class_lowest": dec(line.class_lowest),
                    "position": line.position,
                }
                for line in result.subject_results.all()
            ],
            "summary": _summary(
                result.total,
                result.average,
                result.subjects_count,
                result.position,
                result.out_of,
                result.gpa,
            ),
            "attendance": result.attendance,
            "comments": {
                "form_teacher": result.form_teacher_comment,
                "principal": result.principal_comment,
            },
            "show_position": publication.show_position,
            "use_gpa": publication.use_gpa,
            "grading_scale": publication.grading_scale,
        }
    )
    return card


def live(student, classroom, term):
    """A draft report card from the current scores (staff preview before publishing)."""
    return live_class(classroom, term, [student])[0]


def live_class(classroom, term, students=None):
    """Draft report cards for ``students`` (default: the whole class), computing the class's
    results once."""
    computed = compute_class_results(classroom, term)
    rows = {r["student"].pk: r for r in computed["students"]}
    if students is None:
        students = [r["student"] for r in computed["students"]]
    attendance = class_attendance(classroom, term, students)
    comments = {r.student_id: r for r in TermResult.objects.filter(student__in=students, term=term)}
    school = classroom.school
    form_teacher = classroom.form_teacher.display_name if classroom.form_teacher else ""
    scale = grading_scale(school)
    cards = []
    for student in students:
        row = rows.get(student.pk)
        lines = row["subjects"] if row else []
        summary = row["summary"] if row else {}
        written = comments.get(student.pk)
        card = _header(student, classroom, term, False)
        card.update(
            {
                "form_teacher": form_teacher,
                "subjects": [
                    {
                        "subject": line["subject"].name,
                        "scores": [{**s, "value": dec(s["value"])} for s in line["scores"]],
                        "total": dec(line["total"]),
                        "grade": line["grade"],
                        "remark": line["remark"],
                        "grade_point": dec(line["grade_point"]),
                        "class_average": dec(line["class_average"]),
                        "class_highest": dec(line["class_highest"]),
                        "class_lowest": dec(line["class_lowest"]),
                        "position": line["position"],
                    }
                    for line in lines
                ],
                "summary": _summary(
                    summary.get("total"),
                    summary.get("average"),
                    summary.get("subjects_count", 0),
                    summary.get("position"),
                    summary.get("out_of"),
                    summary.get("gpa"),
                ),
                "attendance": report_card_attendance(attendance[student.pk]),
                "comments": {
                    "form_teacher": written.form_teacher_comment if written else "",
                    "principal": written.principal_comment if written else "",
                },
                "show_position": school.show_position,
                "use_gpa": school.use_gpa,
                "grading_scale": scale,
            }
        )
        cards.append(card)
    return cards
