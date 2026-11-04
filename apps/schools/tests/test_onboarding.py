import pytest

from apps.accounts.models import User
from apps.schools.models import School
from conftest import PASSWORD

pytestmark = pytest.mark.django_db

ONBOARD_URL = "/api/v1/schools/onboard/"


def payload(name="Kings College", system="ng", username="principal", password=PASSWORD):
    return {
        "school_name": name,
        "system": system,
        "admin": {
            "username": username,
            "email": f"{username}@example.com",
            "password": password,
            "first_name": "Ada",
            "last_name": "Obi",
        },
    }


EXPECTED = {
    "ng": {
        "levels": ["JSS1", "JSS2", "JSS3", "SS1", "SS2", "SS3"],
        "terms": ["First Term", "Second Term", "Third Term"],
        "components": {"CA1": 20, "CA2": 20, "Exam": 60},
        "top_grade": "A1",
        "show_position": True,
        "use_gpa": False,
    },
    "uk": {
        "levels": [f"Year {n}" for n in range(7, 14)],
        "terms": ["Autumn Term", "Spring Term", "Summer Term"],
        "components": {"Coursework": 40, "Exam": 60},
        "top_grade": "A*",
        "show_position": False,
        "use_gpa": False,
    },
    "us": {
        "levels": [f"Grade {n}" for n in range(6, 13)],
        "terms": ["Fall Semester", "Spring Semester"],
        "components": {"Homework": 20, "Classwork": 20, "Tests": 30, "Final Exam": 30},
        "top_grade": "A",
        "show_position": False,
        "use_gpa": True,
    },
}


@pytest.mark.parametrize("system", ["ng", "uk", "us"])
def test_onboarding_applies_the_systems_preset(api, system):
    r = api.post(ONBOARD_URL, payload(system=system), format="json")
    assert r.status_code == 201, r.content
    school = School.objects.get()
    want = EXPECTED[system]
    assert [lv.name for lv in school.levels.all()] == want["levels"]
    assert school.term_labels == want["terms"]
    assert {c.name: c.max_score for c in school.components.all()} == want["components"]
    bands = list(school.grade_bands.all())
    assert bands[0].label == want["top_grade"] and bands[-1].min_score == 0
    assert (school.show_position, school.use_gpa) == (want["show_position"], want["use_gpa"])
    assert r.data["school"]["system"] == system


def test_onboarding_creates_first_admin_who_can_log_in(api):
    api.post(ONBOARD_URL, payload(), format="json")
    admin = User.objects.get(username="principal")
    assert admin.role == User.Role.ADMIN
    assert admin.school == School.objects.get()
    assert not admin.is_superuser and not admin.is_staff
    r = api.post("/api/v1/auth/token/", {"username": "principal", "password": PASSWORD})
    assert r.status_code == 200


def test_onboarding_rejects_taken_username(api, make_user):
    make_user("teacher", username="taken")
    r = api.post(ONBOARD_URL, payload(username="taken"), format="json")
    assert r.status_code == 400
    assert not School.objects.filter(name="Kings College").exists()


def test_onboarding_is_all_or_nothing(monkeypatch):
    from apps.schools import services

    def boom(**kwargs):
        raise RuntimeError("admin creation failed")

    monkeypatch.setattr(services.User.objects, "create_user", boom)
    with pytest.raises(RuntimeError):
        services.onboard_school(name="Half Made", system="ng", admin={"username": "x"})
    # the school and its preset rows were rolled back with it
    assert not School.objects.filter(name="Half Made").exists()


def test_onboarding_rejects_weak_password_and_unknown_system(api):
    assert api.post(ONBOARD_URL, payload(password="123"), format="json").status_code == 400
    assert api.post(ONBOARD_URL, payload(system="fr"), format="json").status_code == 400
    assert not School.objects.exists()


def test_same_school_name_gets_distinct_slugs(api):
    api.post(ONBOARD_URL, payload(username="a"), format="json")
    api.post(ONBOARD_URL, payload(username="b"), format="json")
    assert sorted(School.objects.values_list("slug", flat=True)) == [
        "kings-college",
        "kings-college-2",
    ]


# --- editing the setup afterwards -----------------------------------------------------------

ME_URL = "/api/v1/schools/me/"
COMPONENTS_URL = "/api/v1/schools/components/"
BANDS_URL = "/api/v1/schools/grade-bands/"
LEVELS_URL = "/api/v1/schools/levels/"


def test_members_read_school_admins_edit_it(auth, admin_user, make_user):
    teacher = make_user("teacher")
    assert auth(teacher).get(ME_URL).json()["name"] == "Test School"
    assert auth(teacher).patch(ME_URL, {"name": "X"}, format="json").status_code == 403
    r = auth(admin_user).patch(
        ME_URL, {"term_labels": ["Term 1", "Term 2"], "show_position": False}, format="json"
    )
    assert r.status_code == 200, r.content
    assert r.json()["term_labels"] == ["Term 1", "Term 2"]


def test_system_cannot_change_after_onboarding(auth, admin_user, school):
    auth(admin_user).patch(ME_URL, {"system": "us"}, format="json")
    school.refresh_from_db()
    assert school.system == "ng"


def test_term_labels_validated(auth, admin_user):
    for bad in [[], ["A", "a"], ["1", "2", "3", "4", "5"], [""]]:
        r = auth(admin_user).patch(ME_URL, {"term_labels": bad}, format="json")
        assert r.status_code == 400, bad


def test_admin_replaces_score_split(auth, admin_user, school):
    new = {"components": [{"name": "CA", "max_score": 30}, {"name": "Exam", "max_score": 70}]}
    r = auth(admin_user).put(COMPONENTS_URL, new, format="json")
    assert r.status_code == 200, r.content
    assert [(c["name"], c["max_score"], c["order"]) for c in r.json()["components"]] == [
        ("CA", 30, 1),
        ("Exam", 70, 2),
    ]
    assert school.components.count() == 2


def test_score_split_must_add_up_to_100(auth, admin_user, school):
    bad = {"components": [{"name": "CA", "max_score": 30}, {"name": "Exam", "max_score": 60}]}
    r = auth(admin_user).put(COMPONENTS_URL, bad, format="json")
    assert r.status_code == 400
    assert "100" in str(r.json())
    assert school.components.count() == 3  # the preset is untouched


def test_teacher_cannot_change_score_split(auth, make_user):
    teacher = make_user("teacher")
    assert auth(teacher).get(COMPONENTS_URL).status_code == 200
    new = {"components": [{"name": "All", "max_score": 100}]}
    assert auth(teacher).put(COMPONENTS_URL, new, format="json").status_code == 403


def test_admin_replaces_grade_scale(auth, admin_user):
    new = {
        "grade_bands": [
            {"label": "Pass", "min_score": "50", "remark": "Passed"},
            {"label": "Fail", "min_score": "0", "remark": "Failed"},
        ]
    }
    r = auth(admin_user).put(BANDS_URL, new, format="json")
    assert r.status_code == 200, r.content
    assert [b["label"] for b in r.json()["grade_bands"]] == ["Pass", "Fail"]


@pytest.mark.parametrize(
    "bands",
    [
        [{"label": "A", "min_score": "50"}],  # nothing starts at 0
        [{"label": "A", "min_score": "50"}, {"label": "A", "min_score": "0"}],  # same label
        [{"label": "A", "min_score": "0"}, {"label": "B", "min_score": "0"}],  # same minimum
        [{"label": "A", "min_score": "120"}, {"label": "F", "min_score": "0"}],  # over 100
    ],
)
def test_grade_scale_validated(auth, admin_user, bands):
    assert auth(admin_user).put(BANDS_URL, {"grade_bands": bands}, format="json").status_code == 400


def test_admin_adds_level_names_unique_per_school(auth, admin_user, make_user):
    r = auth(admin_user).post(LEVELS_URL, {"name": "Pre-JSS", "order": 0})
    assert r.status_code == 201, r.content
    assert auth(admin_user).post(LEVELS_URL, {"name": "jss1", "order": 9}).status_code == 400
    teacher = make_user("teacher")
    assert auth(teacher).post(LEVELS_URL, {"name": "SS4", "order": 7}).status_code == 403


def test_level_with_classes_cannot_be_deleted(auth, admin_user, school):
    from conftest import make_classroom

    classroom = make_classroom(school, "A")
    url = f"/api/v1/schools/levels/{classroom.level_id}/"
    assert auth(admin_user).delete(url).status_code == 409
    classroom.delete()
    assert auth(admin_user).delete(url).status_code == 204
