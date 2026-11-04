from types import SimpleNamespace

import pytest
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.schools.models import School
from apps.schools.presets import apply_preset

PASSWORD = "Yap-Dev-Pass-9!"  # must pass Django's common-password validator


@pytest.fixture(autouse=True)
def _fast_password_hashing(settings):
    # the production hasher is deliberately slow; tests don't need that
    settings.PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]


def make_school(name, system=School.System.NG):
    """A school with its preset applied and a current session (first term current)."""
    from apps.academics.services import create_session

    school = School.objects.create(name=name, slug=name.lower().replace(" ", "-"), system=system)
    apply_preset(school)
    create_session(school, "2025/2026", make_current=True)
    return school


def make_classroom(school, arm="A", level_order=1):
    from apps.academics.models import Classroom

    return Classroom.objects.create(
        school=school, level=school.levels.get(order=level_order), arm=arm
    )


def assign(teacher, classroom, subject, session=None):
    from apps.academics.models import TeachingAssignment

    session = session or classroom.school.academic_sessions.get(is_current=True)
    return TeachingAssignment.objects.create(
        teacher=teacher, classroom=classroom, subject=subject, session=session
    )


def enroll(student, classroom, session=None):
    from apps.academics.models import Enrollment

    session = session or classroom.school.academic_sessions.get(is_current=True)
    return Enrollment.objects.create(student=student, classroom=classroom, session=session)


@pytest.fixture
def school(db):
    """The school most tests run in."""
    return make_school("Test School")


@pytest.fixture
def other_school(db):
    """A second, unrelated school, for tenant-isolation tests."""
    return make_school("Other School", School.System.UK)


@pytest.fixture
def api():
    return APIClient()


@pytest.fixture
def make_user(db, school):
    counter = {"n": 0}

    def _make(role, username=None, school=school):
        counter["n"] += 1
        return User.objects.create_user(
            username=username or f"{role}_{counter['n']}",
            email=f"{username or role}{counter['n']}@yap.school",
            password=PASSWORD,
            role=role,
            school=school,
        )

    return _make


@pytest.fixture
def admin_user(make_user):
    """The admin of `school` (not a platform superuser)."""
    return make_user("admin", username="admin")


@pytest.fixture
def term(school):
    """The current term of `school`."""
    return school.academic_sessions.get(is_current=True).terms.get(is_current=True)


@pytest.fixture
def kit(make_user, school, term):
    """A class in session: JSS1A, Mathematics taught by `teacher`, `student` enrolled.

    `outsider` is a student of the school who is not in the class; `other_teacher` teaches
    nothing.
    """
    from apps.academics.models import Subject

    classroom = make_classroom(school, "A")
    subject = Subject.objects.create(school=school, name="Mathematics")
    teacher = make_user("teacher")
    student = make_user("student")
    assign(teacher, classroom, subject)
    enroll(student, classroom)
    return SimpleNamespace(
        school=school,
        term=term,
        session=term.session,
        classroom=classroom,
        subject=subject,
        teacher=teacher,
        student=student,
        outsider=make_user("student"),
        other_teacher=make_user("teacher"),
    )


@pytest.fixture
def auth(api):
    def _auth(user):
        from rest_framework_simplejwt.tokens import RefreshToken

        api.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(user).access_token}")
        return api

    return _auth


def results(payload):
    """Unwrap paginated list responses."""
    return payload["results"] if isinstance(payload, dict) and "results" in payload else payload
