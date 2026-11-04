"""Password reset by email: same answer for everyone, one-time links, sessions end."""

import re

import pytest
from django.core import mail

from apps.accounts.models import ActivationCode
from conftest import PASSWORD

pytestmark = pytest.mark.django_db

REQUEST_URL = "/api/v1/auth/password-reset/"
CONFIRM_URL = "/api/v1/auth/password-reset/confirm/"
NEW_PASSWORD = "Remembered-Now-55"


def link_parts(message):
    uid, token = re.search(r"\?uid=([^&\s]+)&token=(\S+)", message.body).groups()
    return uid, token


def ask(api, login):
    api.credentials()
    r = api.post(REQUEST_URL, {"login": login})
    assert r.status_code == 200
    return r.json()


def confirm(api, uid, token, password=NEW_PASSWORD):
    api.credentials()
    return api.post(CONFIRM_URL, {"uid": uid, "token": token, "new_password": password})


def test_reset_by_username_or_email(api, make_user, settings):
    settings.PASSWORD_RESET_URL = "https://app.example.com/reset"
    teacher = make_user("teacher")
    ask(api, teacher.username.upper())
    ask(api, teacher.email)
    assert len(mail.outbox) == 2
    message = mail.outbox[0]
    assert message.to == [teacher.email]
    assert teacher.username in message.body and "Test School" in message.body
    assert "https://app.example.com/reset?uid=" in message.body

    uid, token = link_parts(message)
    r = confirm(api, uid, token)
    assert r.status_code == 200 and "access" in r.json()
    teacher.refresh_from_db()
    assert teacher.check_password(NEW_PASSWORD)
    assert confirm(api, uid, token, "Another-One-77").status_code == 400  # used up
    uid2, token2 = link_parts(mail.outbox[1])  # issued before the change: dead too
    assert confirm(api, uid2, token2, "Another-One-77").status_code == 400


def test_same_answer_whether_or_not_the_account_exists(api, make_user):
    teacher = make_user("teacher")
    no_email = make_user("student")
    no_email.email = ""
    no_email.save()
    answers = {str(ask(api, login)) for login in (teacher.username, "nobody", no_email.username)}
    assert len(answers) == 1
    assert len(mail.outbox) == 1  # only the teacher had an address


def test_shared_family_email_reaches_each_account(api, make_user):
    kids = [make_user("student") for _ in range(2)]
    for kid in kids:
        kid.email = "family@example.com"
        kid.save()
    ask(api, "FAMILY@example.com")
    assert sorted(m.body.split('"')[1] for m in mail.outbox) == sorted(k.username for k in kids)


def test_inactive_people_and_suspended_schools_get_nothing(api, make_user, school):
    user = make_user("teacher")
    user.is_active = False
    user.save()
    ask(api, user.username)
    other = make_user("teacher")
    school.is_active = False
    school.save()
    ask(api, other.username)
    assert mail.outbox == []


def test_reset_ends_sessions_and_uses_up_an_activation_code(api, auth, admin_user, make_user):
    from rest_framework_simplejwt.tokens import RefreshToken

    teacher = make_user("teacher")
    before = str(RefreshToken.for_user(teacher).access_token)  # a session from before
    auth(admin_user).post(f"/api/v1/users/{teacher.pk}/activation-code/")
    ask(api, teacher.username)
    uid, token = link_parts(mail.outbox[0])
    assert confirm(api, uid, token).status_code == 200

    assert not ActivationCode.objects.filter(user=teacher).exists()
    api.credentials(HTTP_AUTHORIZATION=f"Bearer {before}")
    assert api.get("/api/v1/auth/me/").status_code == 401
    api.credentials()
    login = api.post("/api/v1/auth/token/", {"username": teacher.username, "password": PASSWORD})
    assert login.status_code == 401


def test_bad_links_and_weak_passwords(api, make_user):
    teacher = make_user("teacher")
    ask(api, teacher.username)
    uid, token = link_parts(mail.outbox[0])
    for bad_uid, bad_token in (("zzz", token), (uid, "1-abc"), ("", "")):
        assert confirm(api, bad_uid, bad_token).status_code == 400
    weak = confirm(api, uid, token, "password")
    assert weak.status_code == 400 and "new_password" in weak.json()
    assert confirm(api, uid, token).status_code == 200  # the link survived the weak attempt


def test_reset_emails_are_rate_limited_per_person(api, make_user):
    teacher = make_user("teacher")
    for _ in range(3):
        ask(api, teacher.username)
    api.credentials()
    assert api.post(REQUEST_URL, {"login": teacher.username}).status_code == 429
    assert len(mail.outbox) == 3
