"""The questions the access rules keep asking, in one place.

- current_session / current_term: the school's "now"
- teaches: does this teacher hold the assignment for this class + subject in this session?
- teaching_exists / enrolled_exists: the same questions as queryset filters
- children_enrolled_exists / child_param: what a parent sees, through their linked children
"""

from django.db.models import Exists, OuterRef
from rest_framework.exceptions import ValidationError

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


def enrolled_exists(user, prefix="", session_field="term__session"):
    """Filter: rows belonging to a class this student is in, in that row's session."""
    return Exists(
        Enrollment.objects.filter(
            student=user,
            classroom=OuterRef(f"{prefix}classroom"),
            session=OuterRef(f"{prefix}{session_field}"),
        )
    )


def child_param(request):
    """?child=<id>: a parent narrowing a list to one of their children (None: all of them)."""
    value = request.query_params.get("child")
    if not value:
        return None
    if not value.isdigit():
        raise ValidationError({"child": "Must be an ID (a whole number)."})
    return int(value)


def children_of(parent, child=None):
    """Filter kwargs: the students linked to ``parent`` (just ``child`` if given)."""
    lookup = {"student__guardian_links__parent": parent}
    if child is not None:
        lookup["student_id"] = child
    return lookup


def children_enrolled_exists(parent, prefix="", child=None, session_field="term__session"):
    """Filter: rows belonging to a class one of this parent's children is in, in that row's
    session. ``session_field`` is where the row keeps its session (``session`` for rows that
    have one directly, like teaching assignments)."""
    return Exists(
        Enrollment.objects.filter(
            classroom=OuterRef(f"{prefix}classroom"),
            session=OuterRef(f"{prefix}{session_field}"),
            **children_of(parent, child),
        )
    )
