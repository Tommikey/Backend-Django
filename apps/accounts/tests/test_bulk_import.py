"""Bulk import of people from a CSV: preview, row errors, usernames, classes, parent links,
activation codes, tenancy and cost."""

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.academics.models import Enrollment
from apps.accounts.models import ActivationCode, Guardianship, User
from conftest import check, make_classroom, response_schema

pytestmark = pytest.mark.django_db

URL = "/api/v1/imports/people/"
HEADER = "role,first_name,last_name,username,email,classroom,children,relationship\n"


def csv_file(text, name="people.csv", encoding="utf-8"):
    return SimpleUploadedFile(name, text.encode(encoding), content_type="text/csv")


def upload(client, text, commit=False, **kwargs):
    data = {"file": csv_file(text, **kwargs)}
    if commit:
        data["commit"] = "true"
    return client.post(URL, data, format="multipart")


@pytest.fixture
def jss1a(school):
    return make_classroom(school, "A")


def test_the_template_imports_as_is(auth, admin_user, jss1a, api, spec):
    client = auth(admin_user)
    template = client.get(f"{URL}template/")
    assert template.status_code == 200 and template["Content-Type"] == "text/csv"

    r = upload(client, template.content.decode(), commit=True)
    assert r.status_code == 200, r.content
    data = r.json()
    check(spec, response_schema(spec, "imports/people/", "post", 200), data, "import")
    assert data["committed"] and data["valid"]
    assert data["summary"] == {
        "rows": 4,
        "students": 2,
        "teachers": 1,
        "parents": 1,
        "enrollments": 2,
        "parent_links": 2,
    }
    people = {p["username"]: p for p in data["people"]}
    assert set(people) == {"ada.obi", "tunde.b", "ngozi.obi", "musa.ibrahim"}
    assert people["ngozi.obi"]["children"] == ["ada.obi", "tunde.b"]  # "#2" and a username
    assert all(p["activation_code"] for p in people.values())

    ada = User.objects.get(username="ada.obi")
    assert ada.school_id == admin_user.school_id and not ada.has_usable_password()
    assert Enrollment.objects.get(student=ada).classroom == jss1a
    ngozi = User.objects.get(username="ngozi.obi")
    assert Guardianship.objects.filter(parent=ngozi).count() == 2
    assert Guardianship.objects.filter(parent=ngozi).first().relationship == "Mother"
    assert ActivationCode.objects.count() == 4

    # the printed code works
    api.credentials()
    r = api.post(
        "/api/v1/auth/activate/",
        {
            "username": "ada.obi",
            "code": people["ada.obi"]["activation_code"],
            "new_password": "Ada-Chose-This-1",
        },
    )
    assert r.status_code == 200


def test_preview_writes_nothing(auth, admin_user, jss1a):
    r = upload(auth(admin_user), HEADER + "student,Ada,Obi,,,JSS1A,,\n")
    assert r.status_code == 200
    data = r.json()
    assert data["committed"] is False and data["valid"] is True
    assert data["people"][0]["username"] == "ada.obi"
    assert data["people"][0]["activation_code"] is None
    assert not User.objects.filter(username="ada.obi").exists()


def test_row_errors_are_all_reported_and_block_the_import(auth, admin_user, make_user, jss1a):
    make_user("student", username="taken")
    text = HEADER + (
        "pupil,Ada,Obi,,,,,\n"  # 2: role
        "student,,Obi,,,,,\n"  # 3: first name
        "student,Tolu,Ade,,not-an-email,JSS9Z,,\n"  # 4: email, class
        "student,Kemi,Ola,kemi,,,,\n"  # 5
        "student,Kemi,Olu,KEMI,,,,\n"  # 6: same username as row 5
        "student,Bisi,Ade,taken,,,,\n"  # 7: taken
        "teacher,Musa,Ali,,,JSS1A,,\n"  # 8: teachers have no class
        "parent,Ngozi,Obi,,,,#99;ghost,\n"  # 9: bad refs
        "parent,Femi,Obi,,,,#3,Father\n"  # 10: links a broken row
    )
    client = auth(admin_user)
    preview = upload(client, text).json()
    errors = {e["row"]: " ".join(e["messages"]) for e in preview["errors"]}
    assert preview["valid"] is False
    assert set(errors) == {2, 3, 4, 6, 7, 8, 9, 10}
    assert "role" in errors[2] and "first_name" in errors[3]
    assert "email" in errors[4] and "JSS9Z" in errors[4]
    assert "row 5" in errors[6] and "taken" in errors[7]
    assert "classroom" in errors[8]
    assert "#99" in errors[9] and "ghost" in errors[9]
    assert "row 3" in errors[10]

    before = User.objects.count()
    r = upload(client, text, commit=True)
    assert r.status_code == 400 and r.json()["committed"] is False
    assert User.objects.count() == before


def test_usernames_avoid_existing_and_each_other(auth, admin_user, make_user, other_school):
    make_user("teacher", username="ada.obi", school=other_school)  # usernames are global
    text = HEADER + "student,Ada,Obi,,,,,\nstudent,Ada,Obi,,,,,\nstudent,Adá,O'Brien,,,,,\n"
    people = upload(auth(admin_user), text).json()["people"]
    assert [p["username"] for p in people] == ["ada.obi2", "ada.obi3", "ad.obrien"]


def test_spreadsheet_quirks(auth, admin_user, jss1a):
    # Excel: byte-order mark, friendly headers, extra columns, blank lines, spacing in classes
    text = (
        "\ufeffRole,First Name,Surname,Class,Admission No.,Date of Birth\n"
        "Student,Ada,Obi,jss1 a,A/001,2013-01-05\n"
        ",,,,,\n"
        "student,Tunde,Bello,JSS1A,A/002,\n"
    )
    data = upload(auth(admin_user), text, commit=True).json()
    assert data["valid"] and data["summary"]["enrollments"] == 2
    assert data["ignored_columns"] == ["date_of_birth"]
    assert [p["admission_number"] for p in data["people"]] == ["A/001", "A/002"]
    assert [p["row"] for p in data["people"]] == [2, 4]


def test_parents_can_link_existing_students(auth, admin_user, make_user):
    kid = make_user("student", username="old.kid")
    text = HEADER + "parent,Mama,Kid,,,,old.kid,Mother\n"
    upload(auth(admin_user), text, commit=True)
    assert Guardianship.objects.filter(student=kid, parent__username="mama.kid").exists()


def test_only_your_schools_students_and_classes(auth, admin_user, make_user, other_school):
    make_user("student", username="their.kid", school=other_school)
    make_classroom(other_school, "Z")  # e.g. "Year 7Z" there
    text = HEADER + "parent,Mama,X,,,,their.kid,\n"
    errors = upload(auth(admin_user), text).json()["errors"]
    assert "their.kid" in errors[0]["messages"][0]


def test_only_admins_import(auth, make_user):
    teacher = make_user("teacher")
    assert upload(auth(teacher), HEADER + "student,A,B,,,,,\n").status_code == 403
    assert auth(teacher).get(f"{URL}template/").status_code == 403


@pytest.mark.parametrize(
    "text,encoding,message",
    [
        ("name,surname\nAda,Obi\n", "utf-8", "Missing column"),
        ("", "utf-8", "empty"),
        (HEADER, "utf-8", "no people"),
        (HEADER + "student,Adé,Obi,,,,,\n", "utf-16", "UTF-8"),
    ],
)
def test_file_problems(auth, admin_user, text, encoding, message):
    r = upload(auth(admin_user), text, encoding=encoding)
    assert r.status_code == 400 and message in str(r.json()), r.json()


def test_import_cost_does_not_grow_with_rows(auth, admin_user, make_user, jss1a):
    client = auth(admin_user)

    def rows(n, tag):
        lines = [f"student,Kid{tag}{i},Test,,,JSS1A,,\n" for i in range(n)]
        lines.append(f"parent,Mum{tag},Test,,,,#2;#3,Mother\n")
        return HEADER + "".join(lines)

    with CaptureQueriesContext(connection) as small:
        assert upload(client, rows(5, "a"), commit=True).status_code == 200
    with CaptureQueriesContext(connection) as big:
        assert upload(client, rows(60, "b"), commit=True).status_code == 200
    assert len(big) == len(small)


# --- admission numbers -------------------------------------------------------------------------

ADM_HEADER = HEADER.replace("last_name,", "last_name,admission_number,")


def test_admission_numbers_import_and_link_parents(auth, admin_user, make_user, jss1a):
    old = make_user("student", username="old.kid")
    old.admission_number = "DSS/2019/044"
    old.save()
    text = ADM_HEADER + (
        "student,Ada,Obi,DSS/2025/001,,,JSS1A,,\n"
        "parent,Ngozi,Obi,,,,,dss/2025/001; DSS/2019/044,Mother\n"  # any case; new and existing
    )
    data = upload(auth(admin_user), text, commit=True).json()
    assert data["valid"], data["errors"]
    assert User.objects.get(username="ada.obi").admission_number == "DSS/2025/001"
    linked = set(
        Guardianship.objects.filter(parent__username="ngozi.obi").values_list(
            "student__username", flat=True
        )
    )
    assert linked == {"ada.obi", "old.kid"}


def test_admission_number_problems(auth, admin_user, make_user):
    taken = make_user("student")
    taken.admission_number = "A/9"
    taken.save()
    make_user("student", username="A/7")  # a username that is also...
    other = make_user("student")
    other.admission_number = "a/7"  # ...another student's admission number
    other.save()
    text = ADM_HEADER + (
        "student,Ada,Obi,A/1,,,,,\n"  # 2
        "student,Bayo,Ade,a/1,,,,,\n"  # 3: same number as row 2
        "student,Chi,Eze,A/9,,,,,\n"  # 4: taken in the school
        "teacher,Musa,Ali,T/1,,,,,\n"  # 5: teachers have none
        "parent,Mama,Ade,,,,,A/7,\n"  # 6: fits two different students
    )
    errors = {
        e["row"]: " ".join(e["messages"]) for e in upload(auth(admin_user), text).json()["errors"]
    }
    assert set(errors) == {3, 4, 5, 6}
    assert "row 2" in errors[3] and "already belongs" in errors[4]
    assert "Only students" in errors[5] and "#<row>" in errors[6]
