"""Default configuration for each school system, applied once at onboarding.

Schools edit the result afterwards; nothing else in the code branches on the system.
"""

from decimal import Decimal

from .models import AssessmentComponent, GradeBand, Level, School

PRESETS = {
    School.System.NG: {
        "levels": ["JSS1", "JSS2", "JSS3", "SS1", "SS2", "SS3"],
        "term_labels": ["First Term", "Second Term", "Third Term"],
        "components": [("CA1", 20), ("CA2", 20), ("Exam", 60)],
        # WAEC-style scale: (label, min_score, remark, grade_point)
        "grade_bands": [
            ("A1", 75, "Excellent", None),
            ("B2", 70, "Very Good", None),
            ("B3", 65, "Good", None),
            ("C4", 60, "Credit", None),
            ("C5", 55, "Credit", None),
            ("C6", 50, "Credit", None),
            ("D7", 45, "Pass", None),
            ("E8", 40, "Pass", None),
            ("F9", 0, "Fail", None),
        ],
        "show_position": True,
        "use_gpa": False,
    },
    School.System.UK: {
        "levels": [f"Year {n}" for n in range(7, 14)],
        "term_labels": ["Autumn Term", "Spring Term", "Summer Term"],
        "components": [("Coursework", 40), ("Exam", 60)],
        "grade_bands": [
            ("A*", 90, "Outstanding", None),
            ("A", 80, "Excellent", None),
            ("B", 70, "Good", None),
            ("C", 60, "Satisfactory", None),
            ("D", 50, "Below expected", None),
            ("E", 40, "Weak", None),
            ("U", 0, "Ungraded", None),
        ],
        "show_position": False,
        "use_gpa": False,
    },
    School.System.US: {
        "levels": [f"Grade {n}" for n in range(6, 13)],
        "term_labels": ["Fall Semester", "Spring Semester"],
        "components": [("Homework", 20), ("Classwork", 20), ("Tests", 30), ("Final Exam", 30)],
        "grade_bands": [
            ("A", 90, "Excellent", "4.0"),
            ("B", 80, "Good", "3.0"),
            ("C", 70, "Average", "2.0"),
            ("D", 60, "Poor", "1.0"),
            ("F", 0, "Failing", "0.0"),
        ],
        "show_position": False,
        "use_gpa": True,
    },
}


def apply_preset(school):
    """Fill a new school's levels, terms, components and grade bands from its system's preset."""
    preset = PRESETS[school.system]
    school.term_labels = list(preset["term_labels"])
    school.show_position = preset["show_position"]
    school.use_gpa = preset["use_gpa"]
    school.save(update_fields=["term_labels", "show_position", "use_gpa"])

    Level.objects.bulk_create(
        Level(school=school, name=name, order=i) for i, name in enumerate(preset["levels"], 1)
    )
    AssessmentComponent.objects.bulk_create(
        AssessmentComponent(school=school, name=name, max_score=max_score, order=i)
        for i, (name, max_score) in enumerate(preset["components"], 1)
    )
    GradeBand.objects.bulk_create(
        GradeBand(
            school=school,
            label=label,
            min_score=Decimal(min_score),
            remark=remark,
            grade_point=Decimal(point) if point is not None else None,
        )
        for label, min_score, remark, point in preset["grade_bands"]
    )
