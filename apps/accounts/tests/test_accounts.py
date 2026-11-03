import pytest

from apps.accounts.models import User
from conftest import PASSWORD

pytestmark = pytest.mark.django_db


def test_register_defaults_to_student(api):
    r = api.post(
        "/api/v1/auth/register/",
        {"username": "newkid", "email": "kid@yap.school", "password": PASSWORD},
    )
    assert r.status_code == 201, r.content
    assert User.objects.get(username="newkid").role == User.Role.STUDENT


def test_register_teacher(api):
    r = api.post(
        "/api/v1/auth/register/",
        {"username": "newteacher", "email": "t@yap.school", "password": PASSWORD, "role": "teacher"},
    )
    assert r.status_code == 201
    assert User.objects.get(username="newteacher").role == User.Role.TEACHER


def test_register_admin_forbidden(api):
    r = api.post(
        "/api/v1/auth/register/",
        {"username": "hacker", "email": "h@yap.school", "password": PASSWORD, "role": "admin"},
    )
    assert r.status_code == 400
    assert not User.objects.filter(username="hacker").exists()


def test_login_returns_tokens(api, make_user):
    make_user("student", username="kid")
    r = api.post("/api/v1/auth/token/", {"username": "kid", "password": PASSWORD})
    assert r.status_code == 200
    assert "access" in r.data and "refresh" in r.data


def test_me_requires_auth(api):
    assert api.get("/api/v1/auth/me/").status_code == 401


def test_me_returns_own_profile(api, auth, make_user):
    user = make_user("student", username="kid")
    r = auth(user).get("/api/v1/auth/me/")
    assert r.status_code == 200
    assert r.data["username"] == "kid"
    assert r.data["role"] == "student"


def test_superuser_forced_admin_role(db):
    user = User.objects.create_superuser(username="boss", email="b@yap.school", password=PASSWORD)
    assert user.role == User.Role.ADMIN
