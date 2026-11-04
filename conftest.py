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
    school = School.objects.create(name=name, slug=name.lower().replace(" ", "-"), system=system)
    apply_preset(school)
    return school


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
def auth(api):
    def _auth(user):
        from rest_framework_simplejwt.tokens import RefreshToken

        api.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(user).access_token}")
        return api

    return _auth


def results(payload):
    """Unwrap paginated list responses."""
    return payload["results"] if isinstance(payload, dict) and "results" in payload else payload
