"""The questions the access rules keep asking, in one place.

- current_session / current_term: the school's "now"
- teaches: does this teacher hold the assignment for this class + subject in this session?
- teaching_exists / enrolled_exists: the same questions as queryset filters
"""

from django.db.models import Exists, OuterRef

from .models import AcademicSession, Enrollment, TeachingAssignment, Term


def current_session(school_id):
    return AcademicSession.objects.filter(school_id=school_id, is_current=True).first()


def current_term(school_id):
    return (
        Term.objects.select_related("session")
        .filter(session__school_id=school_id, is_current=True)
        .first()
    )


def teaches(user, classroom_id, subject_id, session_id):
    return TeachingAssignment.objects.filter(
        teacher=user, classroom_id=classroom_id, subject_id=subject_id, session_id=session_id
    ).exists()


def teaching_exists(user, prefix=""):
    """Filter: rows whose class + subject + term's session this teacher is assigned to.

    ``prefix`` leads from the row to the object carrying classroom/subject/term, e.g.
    ``assessment__`` for submissions.
    """
    return Exists(
        TeachingAssignment.objects.filter(
            teacher=user,
            classroom=OuterRef(f"{prefix}classroom"),
            subject=OuterRef(f"{prefix}subject"),
            session=OuterRef(f"{prefix}term__session"),
        )
    )


def enrolled_exists(user, prefix=""):
    """Filter: rows belonging to a class this student is in, in that row's session."""
    return Exists(
        Enrollment.objects.filter(
            student=user,
            classroom=OuterRef(f"{prefix}classroom"),
            session=OuterRef(f"{prefix}term__session"),
        )
    )
