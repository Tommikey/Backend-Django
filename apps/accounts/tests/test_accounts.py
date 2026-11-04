import pytest

from apps.accounts.models import Guardianship, User
from conftest import PASSWORD, results

pytestmark = pytest.mark.django_db

USERS_URL = "/api/v1/users/"
LINKS_URL = "/api/v1/guardianships/"


def new_user(role, username, **extra):
    return {
        "username": username,
        "email": f"{username}@yap.school",
        "password": PASSWORD,
        "role": role,
        **extra,
    }


def test_public_self_registration_is_gone(api):
    r = api.post("/api/v1/auth/register/", new_user("student", "newkid"))
    assert r.status_code == 404


def test_login_returns_tokens(api, make_user):
    make_user("student", username="kid")
    r = api.post("/api/v1/auth/token/", {"username": "kid", "password": PASSWORD})
    assert r.status_code == 200
    assert "access" in r.data and "refresh" in r.data


def test_me_requires_auth(api):
    assert api.get("/api/v1/auth/me/").status_code == 401


def test_me_returns_own_profile_with_school(auth, make_user, school):
    user = make_user("student", username="kid")
    r = auth(user).get("/api/v1/auth/me/")
    assert r.status_code == 200
    assert r.data["username"] == "kid"
    assert r.data["role"] == "student"
    assert r.data["school"] == school.pk
    assert r.data["school_name"] == "Test School"


def test_superuser_forced_admin_role(db):
    user = User.objects.create_superuser(username="boss", email="b@yap.school", password=PASSWORD)
    assert user.role == User.Role.ADMIN
    assert user.school is None


@pytest.mark.parametrize("role", ["teacher", "student", "parent", "admin"])
def test_admin_creates_users_in_own_school(auth, admin_user, school, role):
    r = auth(admin_user).post(USERS_URL, new_user(role, f"new_{role}"))
    assert r.status_code == 201, r.content
    created = User.objects.get(username=f"new_{role}")
    assert created.school == school
    assert created.role == role
    assert created.check_password(PASSWORD)
    assert "password" not in r.data


def test_school_cannot_be_chosen_on_create(auth, admin_user, school, other_school):
    r = auth(admin_user).post(USERS_URL, new_user("student", "sneaky", school=other_school.pk))
    assert r.status_code == 201
    assert User.objects.get(username="sneaky").school == school


def test_create_user_requires_strong_password(auth, admin_user):
    r = auth(admin_user).post(USERS_URL, {**new_user("student", "nopass"), "password": ""})
    assert r.status_code == 400
    r = auth(admin_user).post(USERS_URL, {**new_user("student", "weak"), "password": "1234"})
    assert r.status_code == 400
    assert not User.objects.filter(username__in=["nopass", "weak"]).exists()


def test_admin_resets_password(auth, admin_user, make_user):
    student = make_user("student")
    r = auth(admin_user).patch(f"{USERS_URL}{student.pk}/", {"password": "Fresh-Pass-2026!"})
    assert r.status_code == 200, r.content
    student.refresh_from_db()
    assert student.check_password("Fresh-Pass-2026!")


def test_only_admins_manage_users(auth, make_user):
    teacher = make_user("teacher")
    student = make_user("student")
    assert auth(teacher).post(USERS_URL, new_user("student", "x")).status_code == 403
    assert auth(teacher).get(USERS_URL).status_code == 200  # teachers can look people up
    assert auth(student).get(USERS_URL).status_code == 403


def test_users_list_filters_by_role(auth, admin_user, make_user):
    make_user("teacher")
    make_user("student")
    make_user("student")
    rows = results(auth(admin_user).get(f"{USERS_URL}?role=student").json())
    assert len(rows) == 2 and {r["role"] for r in rows} == {"student"}


def test_admin_cannot_delete_self(auth, admin_user):
    assert auth(admin_user).delete(f"{USERS_URL}{admin_user.pk}/").status_code == 400


# --- parents ---------------------------------------------------------------------------


def test_admin_links_parent_to_student(auth, admin_user, make_user):
    parent, student = make_user("parent"), make_user("student")
    r = auth(admin_user).post(
        LINKS_URL, {"parent": parent.pk, "student": student.pk, "relationship": "Mother"}
    )
    assert r.status_code == 201, r.content
    assert Guardianship.objects.filter(parent=parent, student=student).exists()


def test_link_checks_roles(auth, admin_user, make_user):
    teacher, student = make_user("teacher"), make_user("student")
    r = auth(admin_user).post(LINKS_URL, {"parent": teacher.pk, "student": student.pk})
    assert r.status_code == 400
    assert "parent" in r.json()


def test_parent_sees_only_own_links(auth, make_user):
    mum, other_parent = make_user("parent"), make_user("parent")
    kid, other_kid = make_user("student"), make_user("student")
    Guardianship.objects.create(parent=mum, student=kid)
    Guardianship.objects.create(parent=other_parent, student=other_kid)
    rows = results(auth(mum).get(LINKS_URL).json())
    assert [r["student"] for r in rows] == [kid.pk]


def test_parents_cannot_create_links(auth, make_user):
    parent, student = make_user("parent"), make_user("student")
    r = auth(parent).post(LINKS_URL, {"parent": parent.pk, "student": student.pk})
    assert r.status_code == 403


# --- keeping school records safe ---------------------------------------------------------------


def test_deleting_someone_with_records_is_refused(auth, admin_user, kit):
    from apps.results.models import Score

    component = kit.school.components.first()
    Score.objects.create(
        student=kit.student, subject=kit.subject, term=kit.term, component=component, value=10
    )
    for person in (kit.student, kit.teacher):  # enrolled / assigned
        r = auth(admin_user).delete(f"{USERS_URL}{person.pk}/")
        assert r.status_code == 409 and "Deactivate" in r.json()["detail"]
    assert Score.objects.filter(student=kit.student).exists()

    # deactivating is the way out; a fresh account with no records can still be deleted
    r = auth(admin_user).patch(f"{USERS_URL}{kit.student.pk}/", {"is_active": False})
    assert r.status_code == 200 and r.json()["is_active"] is False
    assert auth(admin_user).delete(f"{USERS_URL}{kit.outsider.pk}/").status_code == 204


def test_roles_are_fixed_after_creation(auth, admin_user, make_user):
    student = make_user("student")
    r = auth(admin_user).patch(f"{USERS_URL}{student.pk}/", {"role": "teacher"})
    assert r.status_code == 400 and "role" in r.json()
    r = auth(admin_user).patch(f"{USERS_URL}{admin_user.pk}/", {"role": "teacher"})
    assert r.status_code == 400
    # sending the same role back (a full PUT from a form) is fine
    r = auth(admin_user).patch(
        f"{USERS_URL}{student.pk}/", {"role": "student", "first_name": "Ada"}
    )
    assert r.status_code == 200


def test_school_keeps_an_active_admin(auth, admin_user, make_user):
    r = auth(admin_user).patch(f"{USERS_URL}{admin_user.pk}/", {"is_active": False})
    assert r.status_code == 400  # not yourself
    second = make_user("admin")
    r = auth(second).patch(f"{USERS_URL}{admin_user.pk}/", {"is_active": False})
    assert r.status_code == 200  # the admin doing it is still active
    r = auth(second).patch(f"{USERS_URL}{admin_user.pk}/", {"is_active": True})
    assert r.status_code == 200


def test_usernames_are_case_insensitive(auth, admin_user, make_user):
    make_user("student", username="Chidi")
    r = auth(admin_user).post(USERS_URL, new_user("student", "chidi"))
    assert r.status_code == 400 and "username" in r.json()


def test_suspended_school_is_locked_out(api, auth, make_user, school):
    user = make_user("teacher")
    tokens = api.post(
        "/api/v1/auth/token/", {"username": user.username, "password": PASSWORD}
    ).json()
    client = auth(user)
    assert client.get("/api/v1/auth/me/").status_code == 200

    school.is_active = False
    school.save()
    assert client.get("/api/v1/auth/me/").status_code == 401  # existing access token
    api.credentials()
    login = api.post("/api/v1/auth/token/", {"username": user.username, "password": PASSWORD})
    assert login.status_code == 401
    refresh = api.post("/api/v1/auth/token/refresh/", {"refresh": tokens["refresh"]})
    assert refresh.status_code == 401
