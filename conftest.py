from types import SimpleNamespace

import pytest
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.schools.models import School
from apps.schools.presets import apply_preset

PASSWORD = "Yap-Dev-Pass-9!"  # must pass Django's common-password validator


@pytest.fixture(autouse=True)
def _fresh_rate_limits():
    # throttle counters live in the cache; don't let them leak between tests
    from django.core.cache import cache

    cache.clear()


@pytest.fixture(autouse=True)
def _plain_http(settings):
    # CI runs with DEBUG=False, which turns on HTTPS redirects; the test client speaks HTTP
    settings.SECURE_SSL_REDIRECT = False


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


# --- checking responses against the API docs ------------------------------------------------


@pytest.fixture(scope="session")
def spec():
    """The generated OpenAPI schema, for checking responses against the docs (``check``)."""
    from drf_spectacular.generators import SchemaGenerator

    return SchemaGenerator().get_schema(request=None, public=True)


def resolve(spec, schema):
    while "$ref" in schema:
        schema = spec["components"]["schemas"][schema["$ref"].split("/")[-1]]
    if "allOf" in schema:  # a nullable $ref is wrapped as allOf + nullable
        merged = resolve(spec, schema["allOf"][0])
        return {**merged, "nullable": schema.get("nullable", False)}
    return schema


def check(spec, schema, value, where="$"):
    schema = resolve(spec, schema)
    if value is None:
        assert schema.get("nullable"), f"{where} is null but not documented as nullable"
        return
    if "properties" in schema:
        assert isinstance(value, dict), where
        documented, actual = set(schema["properties"]), set(value)
        assert actual == documented, (
            f"{where}: undocumented {actual - documented}, missing {documented - actual}"
        )
        for key, sub in schema["properties"].items():
            check(spec, sub, value[key], f"{where}.{key}")
    elif schema.get("type") == "array":
        assert isinstance(value, list), where
        for i, item in enumerate(value[:3]):
            check(spec, schema["items"], item, f"{where}[{i}]")
    elif isinstance(schema.get("additionalProperties"), dict):
        for key, item in value.items():
            check(spec, schema["additionalProperties"], item, f"{where}[{key}]")


def response_schema(spec, path, method, status):
    op = spec["paths"][f"/api/v1/{path}"][method]
    return op["responses"][str(status)]["content"]["application/json"]["schema"]
