"""Activation codes: issued by an admin (or an import), used once to choose a password."""

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.accounts.models import ActivationCode
from conftest import results

pytestmark = pytest.mark.django_db

ACTIVATE_URL = "/api/v1/auth/activate/"
NEW_PASSWORD = "My-Own-Choice-2026"


def issue(auth, admin, user):
    r = auth(admin).post(f"/api/v1/users/{user.pk}/activation-code/")
    assert r.status_code == 201, r.content
    return r.json()["code"]


def activate(api, user, code, password=NEW_PASSWORD):
    api.credentials()
    return api.post(
        ACTIVATE_URL, {"username": user.username, "code": code, "new_password": password}
    )


def test_issue_and_activate(api, auth, admin_user, make_user):
    student = make_user("student")
    code = issue(auth, admin_user, student)
    assert len(code) == 9 and code[4] == "-"
    assert not ActivationCode.objects.filter(code_hash__contains=code).exists()  # hashed

    # typed loosely: lower case, no dash, and the username in another case
    api.credentials()
    r = api.post(
        ACTIVATE_URL,
        {
            "username": student.username.upper(),
            "code": code.lower().replace("-", ""),
            "new_password": NEW_PASSWORD,
        },
    )
    assert r.status_code == 200, r.content
    assert {"access", "refresh"} <= set(r.json())
    student.refresh_from_db()
    assert student.check_password(NEW_PASSWORD)
    assert not ActivationCode.objects.filter(user=student).exists()
    assert activate(api, student, code).status_code == 400  # single use


def test_wrong_details_all_look_the_same(api, auth, admin_user, make_user):
    student = make_user("student")
    code = issue(auth, admin_user, student)
    wrong_code = activate(api, student, "AAAA-AAAA").json()
    api.credentials()
    nobody = api.post(
        ACTIVATE_URL, {"username": "nobody", "code": code, "new_password": NEW_PASSWORD}
    ).json()
    assert wrong_code == nobody


def test_expired_reissued_and_inactive_codes_fail(api, auth, admin_user, make_user):
    student = make_user("student")
    old = issue(auth, admin_user, student)
    new = issue(auth, admin_user, student)
    assert activate(api, student, old).status_code == 400  # replaced

    ActivationCode.objects.filter(user=student).update(
        expires_at=timezone.now() - timedelta(minutes=1)
    )
    assert activate(api, student, new).status_code == 400

    fresh = issue(auth, admin_user, student)
    student.is_active = False
    student.save()
    assert activate(api, student, fresh).status_code == 400


def test_weak_password_keeps_the_code(api, auth, admin_user, make_user):
    student = make_user("student")
    code = issue(auth, admin_user, student)
    r = activate(api, student, code, password="12345678")
    assert r.status_code == 400
    assert activate(api, student, code).status_code == 200


def test_reissue_works_as_a_reset(api, auth, admin_user, make_user):
    student = make_user("student")
    session = auth(student).get("/api/v1/auth/me/")
    assert session.status_code == 200
    code = issue(auth, admin_user, student)
    assert activate(api, student, code).status_code == 200
    from conftest import PASSWORD

    api.credentials()
    old = api.post("/api/v1/auth/token/", {"username": student.username, "password": PASSWORD})
    assert old.status_code == 401


def test_only_admins_issue_codes_in_their_school(auth, admin_user, make_user, other_school):
    student = make_user("student")
    teacher = make_user("teacher")
    assert auth(teacher).post(f"/api/v1/users/{student.pk}/activation-code/").status_code == 403
    theirs = make_user("student", school=other_school)
    r = auth(admin_user).post(f"/api/v1/users/{theirs.pk}/activation-code/")
    assert r.status_code == 404


def test_people_list_shows_who_has_not_activated(auth, admin_user, make_user):
    student = make_user("student")
    student.set_unusable_password()
    student.save()
    issue(auth, admin_user, student)
    rows = {u["id"]: u for u in results(auth(admin_user).get("/api/v1/users/").json())}
    assert rows[student.pk]["has_password"] is False
    assert rows[student.pk]["activation_expires_at"] is not None
    assert rows[admin_user.pk]["has_password"] is True
    assert rows[admin_user.pk]["activation_expires_at"] is None


def test_guessing_is_rate_limited(api, auth, admin_user, make_user):
    student = make_user("student")
    issue(auth, admin_user, student)
    codes = [activate(api, student, f"AAAA-AA{i:02d}").status_code for i in range(11)]
    assert codes[-1] == 429 and set(codes[:10]) == {400}
