from django.db import transaction

from .models import AcademicSession, Term


@transaction.atomic
def create_session(school, name, starts_on=None, ends_on=None, make_current=False):
    """Create a session with one term per name in the school's term_labels."""
    session = AcademicSession.objects.create(
        school=school, name=name, starts_on=starts_on, ends_on=ends_on
    )
    Term.objects.bulk_create(
        Term(session=session, name=label, order=i)
        for i, label in enumerate(school.term_labels, 1)
    )
    if make_current:
        make_term_current(session.terms.order_by("order").first())
    return session


@transaction.atomic
def make_term_current(term):
    """Make ``term`` (and its session) the school's current ones; unset any others."""
    session = term.session
    school_id = session.school_id
    AcademicSession.objects.filter(school_id=school_id).exclude(pk=session.pk).update(
        is_current=False
    )
    Term.objects.filter(session__school_id=school_id).exclude(pk=term.pk).update(is_current=False)
    AcademicSession.objects.filter(pk=session.pk).update(is_current=True)
    Term.objects.filter(pk=term.pk).update(is_current=True)
    session.is_current = term.is_current = True
    return term
