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


def test_login_is_rate_limited_per_username(api, make_user):
    user = make_user("student")
    for _ in range(10):
        api.post("/api/v1/auth/token/", {"username": user.username, "password": "wrong"})
    r = api.post("/api/v1/auth/token/", {"username": user.username.upper(), "password": PASSWORD})
    assert r.status_code == 429  # even the right password, until the window passes
    other = make_user("student")
    r = api.post("/api/v1/auth/token/", {"username": other.username, "password": PASSWORD})
    assert r.status_code == 200  # a classmate on the same IP is unaffected


def test_onboarding_is_rate_limited(api):
    for _ in range(10):
        api.post("/api/v1/schools/onboard/", {})
    assert api.post("/api/v1/schools/onboard/", {}).status_code == 429


# --- sessions --------------------------------------------------------------------------------

TOKEN_URL = "/api/v1/auth/token/"
REFRESH_URL = "/api/v1/auth/token/refresh/"
NEW_PASSWORD = "Fresh-Start-2026!"


def login(api, user, password=PASSWORD):
    r = api.post(TOKEN_URL, {"username": user.username, "password": password})
    assert r.status_code == 200, r.content
    return r.json()


def bearer(api, access):
    api.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
    return api


def test_logout_retires_the_refresh_token(api, make_user):
    tokens = login(api, make_user("student"))
    assert api.post("/api/v1/auth/logout/", {"refresh": tokens["refresh"]}).status_code == 200
    assert api.post(REFRESH_URL, {"refresh": tokens["refresh"]}).status_code == 401


def test_refresh_rotates(api, make_user):
    tokens = login(api, make_user("student"))
    rotated = api.post(REFRESH_URL, {"refresh": tokens["refresh"]}).json()
    assert rotated["refresh"] != tokens["refresh"]
    assert api.post(REFRESH_URL, {"refresh": tokens["refresh"]}).status_code == 401  # used up


def test_change_own_password_ends_other_sessions(api, make_user):
    user = make_user("teacher")
    phone = login(api, user)
    laptop = login(api, user)

    r = bearer(api, laptop["access"]).post(
        "/api/v1/auth/password/",
        {"current_password": PASSWORD, "new_password": NEW_PASSWORD},
    )
    assert r.status_code == 200, r.content
    fresh = r.json()

    assert bearer(api, phone["access"]).get("/api/v1/auth/me/").status_code == 401
    api.credentials()
    assert api.post(REFRESH_URL, {"refresh": phone["refresh"]}).status_code == 401
    assert bearer(api, fresh["access"]).get("/api/v1/auth/me/").status_code == 200
    api.credentials()
    login(api, user, NEW_PASSWORD)


def test_password_change_checks(api, make_user):
    user = make_user("student")
    client = bearer(api, login(api, user)["access"])
    url = "/api/v1/auth/password/"
    wrong = client.post(url, {"current_password": "nope", "new_password": NEW_PASSWORD})
    assert wrong.status_code == 400 and "current_password" in wrong.json()
    weak = client.post(url, {"current_password": PASSWORD, "new_password": "12345678"})
    assert weak.status_code == 400
    api.credentials()
    assert api.post(url, {}).status_code == 401


def test_admin_reset_ends_the_users_sessions(api, auth, admin_user, make_user):
    student = make_user("student")
    tokens = login(api, student)
    r = auth(admin_user).patch(f"{USERS_URL}{student.pk}/", {"password": NEW_PASSWORD})
    assert r.status_code == 200
    assert bearer(api, tokens["access"]).get("/api/v1/auth/me/").status_code == 401
    api.credentials()
    assert api.post(REFRESH_URL, {"refresh": tokens["refresh"]}).status_code == 401


# --- me: what a client needs to start ---------------------------------------------------------

ME_URL = "/api/v1/auth/me/"


def test_me_bootstraps_a_teacher(auth, kit):
    kit.classroom.form_teacher = kit.teacher
    kit.classroom.save()
    data = auth(kit.teacher).get(ME_URL).json()
    assert data["school_details"]["system"] == "ng"
    assert data["school_details"]["term_labels"] == ["First Term", "Second Term", "Third Term"]
    assert data["current_session"] == {"id": kit.session.pk, "name": "2025/2026"}
    assert data["current_term"]["id"] == kit.term.pk
    assert data["form_classes"] == [{"id": kit.classroom.pk, "name": "JSS1A"}]
    assert data["teaching"] == [
        {
            "classroom": {"id": kit.classroom.pk, "name": "JSS1A"},
            "subject": {"id": kit.subject.pk, "name": "Mathematics"},
        }
    ]
    assert data["classroom"] is None and data["children"] == []


def test_me_bootstraps_a_student_and_a_parent(auth, kit, make_user):
    data = auth(kit.student).get(ME_URL).json()
    assert data["classroom"] == {"id": kit.classroom.pk, "name": "JSS1A"}
    assert data["teaching"] == [] and data["form_classes"] == []

    parent = make_user("parent")
    Guardianship.objects.create(parent=parent, student=kit.student, relationship="Mother")
    Guardianship.objects.create(parent=parent, student=kit.outsider)  # in no class
    children = auth(parent).get(ME_URL).json()["children"]
    by_id = {c["id"]: c for c in children}
    assert by_id[kit.student.pk]["classroom"]["name"] == "JSS1A"
    assert by_id[kit.student.pk]["relationship"] == "Mother"
    assert by_id[kit.outsider.pk]["classroom"] is None


def test_me_query_count_is_flat(auth, kit, make_user, django_assert_max_num_queries):
    parent = make_user("parent")
    for _ in range(5):
        child = make_user("student")
        from conftest import enroll

        enroll(child, kit.classroom)
        Guardianship.objects.create(parent=parent, student=child)
    with django_assert_max_num_queries(8):
        assert auth(parent).get(ME_URL).status_code == 200


def test_me_patch_edits_profile_only(auth, kit):
    r = auth(kit.student).patch(ME_URL, {"first_name": "Ada", "role": "admin"})
    assert r.status_code == 200
    kit.student.refresh_from_db()
    assert kit.student.first_name == "Ada" and kit.student.role == "student"
    assert r.json()["classroom"]["name"] == "JSS1A"


def test_me_for_platform_staff(auth, db):
    boss = User.objects.create_superuser(username="root", email="r@yap.school", password=PASSWORD)
    data = auth(boss).get(ME_URL).json()
    assert data["school_details"] is None and data["current_term"] is None
