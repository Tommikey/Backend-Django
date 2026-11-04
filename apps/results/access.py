"""Who may do what with results.

- scores: the subject's assigned teacher (or an admin) enters them; the form teacher can look
- class broadsheet and draft report cards: admins and the class's form teacher
- comments: the form teacher writes theirs, the admin writes the principal's
- published report cards: also the student themself and their linked parents
"""

from apps.academics.rules import teaches
from apps.accounts.models import Guardianship, User


def is_admin(user):
    return user.role == User.Role.ADMIN


def is_form_teacher(user, classroom):
    return classroom.form_teacher_id is not None and classroom.form_teacher_id == user.pk


def can_enter_scores(user, classroom, subject, term):
    return is_admin(user) or (
        user.role == User.Role.TEACHER and teaches(user, classroom.pk, subject.pk, term.session_id)
    )


def can_view_scores(user, classroom, subject, term):
    return can_enter_scores(user, classroom, subject, term) or is_form_teacher(user, classroom)


def can_review_class(user, classroom):
    """Broadsheet, draft report cards."""
    return is_admin(user) or is_form_teacher(user, classroom)


def can_read_published_card(user, student, classroom):
    if can_review_class(user, classroom) or user.pk == student.pk:
        return True
    return (
        user.role == User.Role.PARENT
        and Guardianship.objects.filter(parent=user, student=student).exists()
    )
