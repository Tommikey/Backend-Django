"""Report cards as JSON, in one shape whether read from a published snapshot or previewed
live (draft) from current scores.
"""

from apps.attendance.services import class_attendance, report_card_attendance

from .models import TermResult
from .services import compute_class_results, dec, grading_scale


def _header(student, classroom, term, published, publication=None):
    school = classroom.school
    return {
        "published": published,
        "published_at": publication.published_at if publication else None,
        "school": {"name": school.name, "system": school.system},
        "student": {"id": student.pk, "name": student.display_name},
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
    computed = compute_class_results(classroom, term)
    row = next((r for r in computed["students"] if r["student"].pk == student.pk), None)
    lines = row["subjects"] if row else []
    summary = row["summary"] if row else {}
    comments = TermResult.objects.filter(student=student, term=term).first()
    school = classroom.school
    card = _header(student, classroom, term, False)
    card.update(
        {
            "form_teacher": classroom.form_teacher.display_name if classroom.form_teacher else "",
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
            "attendance": report_card_attendance(
                class_attendance(classroom, term, [student])[student.pk]
            ),
            "comments": {
                "form_teacher": comments.form_teacher_comment if comments else "",
                "principal": comments.principal_comment if comments else "",
            },
            "show_position": school.show_position,
            "use_gpa": school.use_gpa,
            "grading_scale": grading_scale(school),
        }
    )
    return card
