"""Printable report cards: the same cards and the same access rules as the JSON, as PDF."""

from io import BytesIO

import pytest
from pypdf import PdfReader

from apps.accounts.models import Guardianship
from apps.results import pdf
from apps.results.tests.test_api import sheet_body
from conftest import enroll

pytestmark = pytest.mark.django_db

CARD_URL = "/api/v1/results/report-card/pdf/"
CLASS_URL = "/api/v1/results/report-cards/pdf/"


def pages(response):
    assert response.status_code == 200, response.content[:300]
    assert response["Content-Type"] == "application/pdf"
    assert response.content.startswith(b"%PDF")
    return [page.extract_text() for page in PdfReader(BytesIO(response.content)).pages]


@pytest.fixture
def cards(kit, make_user):
    """kit with a Yoruba-named classmate, marks for both and a form teacher."""
    kit.student.first_name, kit.student.last_name = "Ọlá", "Àdébáyọ̀"
    kit.student.admission_number = "YAP/2025/001"
    kit.student.save()
    kit.classmate = make_user("student")
    kit.classmate.first_name, kit.classmate.last_name = "Chidi", "Eze"
    kit.classmate.save()
    enroll(kit.classmate, kit.classroom)
    kit.classroom.form_teacher = kit.teacher
    kit.classroom.save()
    return kit


def mark(auth, kit, student, **marks):
    r = auth(kit.teacher).put(
        "/api/v1/results/score-sheet/", sheet_body(kit, student=student, **marks), format="json"
    )
    assert r.status_code == 200, r.content


def test_published_card(auth, cards, admin_user, make_user):
    mark(auth, cards, cards.student, CA1=18, CA2=17, Exam=55)
    mark(auth, cards, cards.classmate, CA1=10, CA2=12, Exam=40)
    auth(cards.teacher).put(
        "/api/v1/results/comments/",
        {"student": cards.student.pk, "form_teacher_comment": "Ọlá did very well."},
        format="json",
    )
    assert auth(admin_user).post("/api/v1/results/publish/", {}).status_code == 202

    parent = make_user("parent")
    Guardianship.objects.create(parent=parent, student=cards.student)
    for reader in (cards.student, parent, cards.teacher, admin_user):
        query = {} if reader == cards.student else {"student": cards.student.pk}
        r = auth(reader).get(CARD_URL, query)
        [text] = pages(r)
        assert "Ọlá Àdébáyọ̀" in text  # printed, not boxes
        assert "YAP/2025/001" in text and "JSS1A" in text and "Mathematics" in text
        assert "Ọlá did very well." in text
        assert "90" in text  # 18 + 17 + 55
        assert "Published on" in text and "DRAFT" not in text
    assert r["Content-Disposition"].startswith("inline")
    assert "First%20Term" in r["Content-Disposition"]
    assert r["Cache-Control"] == "private, no-store"
    saved = auth(parent).get(CARD_URL, {"student": cards.student.pk, "download": "true"})
    assert saved["Content-Disposition"].startswith("attachment")

    # someone else's child, or a classmate: nothing
    assert auth(make_user("parent")).get(CARD_URL, {"student": cards.student.pk}).status_code == 404
    assert auth(cards.classmate).get(CARD_URL, {"student": cards.student.pk}).status_code == 404


def test_drafts_are_marked_and_staff_only(auth, cards, admin_user):
    mark(auth, cards, cards.student, CA1=18)
    [text] = pages(auth(admin_user).get(CARD_URL, {"student": cards.student.pk}))
    assert "Draft: not published" in text and "DRAFT" in text
    assert auth(cards.student).get(CARD_URL).status_code == 404  # not published yet
    assert auth(cards.other_teacher).get(CARD_URL, {"student": cards.student.pk}).status_code == 404


def test_whole_class_in_one_document(auth, cards, admin_user, django_assert_max_num_queries):
    mark(auth, cards, cards.student, CA1=18, CA2=17, Exam=55)
    mark(auth, cards, cards.classmate, CA1=10, CA2=12, Exam=40)
    query = {"classroom": cards.classroom.pk}

    draft = pages(auth(cards.teacher).get(CLASS_URL, query))  # the form teacher
    assert len(draft) == 2
    assert "Chidi Eze" in draft[0] or "Chidi Eze" in draft[1]

    auth(admin_user).post("/api/v1/results/publish/", {})
    client = auth(admin_user)
    with django_assert_max_num_queries(25):
        published = pages(client.get(CLASS_URL, query))
    assert len(published) == 2 and all("Published on" in page for page in published)
    assert ["Àdébáyọ̀" in published[0], "Eze" in published[1]] == [True, True]  # by surname

    assert auth(cards.other_teacher).get(CLASS_URL, query).status_code == 403
    assert auth(cards.student).get(CLASS_URL, query).status_code == 403


def test_class_drafts_compute_once(
    auth, cards, admin_user, make_user, django_assert_max_num_queries
):
    for _ in range(8):
        enroll(make_user("student"), cards.classroom)
    with django_assert_max_num_queries(30):  # not one results computation per student
        assert len(pages(auth(admin_user).get(CLASS_URL, {"classroom": cards.classroom.pk}))) == 10


def test_number_formatting():
    assert [pdf.num(v) for v in ("12.00", "12.50", None, "0.00", 7)] == [
        "12",
        "12.5",
        "–",
        "0",
        "7",
    ]
    assert [pdf.ordinal(n) for n in (1, 2, 3, 4, 11, 12, 13, 21, 22, 101, 111)] == [
        "1st", "2nd", "3rd", "4th", "11th", "12th", "13th", "21st", "22nd", "101st", "111th",
    ]  # fmt: skip
    assert pdf.filename("Ọlá Àdé", "First Term 2025/2026") == "Ọlá Àdé - First Term 2025-2026.pdf"
    assert pdf.filename("../../etc", "x") == "..-..-etc - x.pdf"  # no path separators survive
