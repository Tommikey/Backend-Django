import pytest
from rest_framework.test import APIClient

from apps.accounts.models import User

PASSWORD = "Yap-Dev-Pass-9!"  # must pass Django's common-password validator


@pytest.fixture
def api():
    return APIClient()


@pytest.fixture
def make_user(db):
    counter = {"n": 0}

    def _make(role, username=None):
        counter["n"] += 1
        return User.objects.create_user(
            username=username or f"{role}_{counter['n']}",
            email=f"{username or role}{counter['n']}@yap.school",
            password=PASSWORD,
            role=role,
        )

    return _make


@pytest.fixture
def admin_user(db):
    return User.objects.create_superuser(username="admin", email="admin@yap.school", password=PASSWORD)


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
