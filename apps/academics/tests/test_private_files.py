"""Uploaded files are private: random storage names, downloads only through endpoints that
check who may see the lesson or submission, and cleanup when files are replaced or deleted."""

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.academics.models import Lesson
from apps.accounts.models import Guardianship
from apps.assessments.models import Assessment, Submission

pytestmark = pytest.mark.django_db

LESSONS_URL = "/api/v1/academics/lessons/"


@pytest.fixture
def media(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    return tmp_path


def pdf(name="Week 1 Notes.pdf", body=b"%PDF-1.7 fractions"):
    return SimpleUploadedFile(name, body, content_type="application/pdf")


def post_lesson(auth, kit, upload):
    body = {"title": "Fractions", "classroom": kit.classroom.pk, "subject": kit.subject.pk}
    r = auth(kit.teacher).post(LESSONS_URL, {**body, "file": upload}, format="multipart")
    assert r.status_code == 201, r.content
    return r.json()


def body_of(response):
    return b"".join(response.streaming_content)


def test_lesson_file_is_stored_privately_and_linked(auth, kit, media):
    data = post_lesson(auth, kit, pdf())
    lesson = Lesson.objects.get(pk=data["id"])
    assert data["file"] == f"http://testserver{LESSONS_URL}{lesson.pk}/file/"
    assert data["file_name"] == "Week 1 Notes.pdf"
    assert "Week" not in lesson.file.name and lesson.file.name.startswith("lessons/")
    assert (media / lesson.file.name).exists()


def test_who_can_download_a_lesson_file(auth, kit, media, make_user, other_school):
    lesson_id = post_lesson(auth, kit, pdf())["id"]
    url = f"{LESSONS_URL}{lesson_id}/file/"
    parent = make_user("parent")
    Guardianship.objects.create(parent=parent, student=kit.student)
    for reader in (kit.teacher, kit.student, parent):
        r = auth(reader).get(url)
        assert r.status_code == 200, reader.role
        assert body_of(r) == b"%PDF-1.7 fractions"
        assert r["Content-Type"] == "application/pdf"
        assert (
            r["Content-Disposition"].startswith("inline")
            and "Week 1 Notes.pdf" in r["Content-Disposition"]
        )
        assert r["Cache-Control"] == "private, no-store"
    for stranger in (kit.outsider, make_user("parent"), make_user("admin", school=other_school)):
        assert auth(stranger).get(url).status_code == 404


def test_documents_download_rather_than_open(auth, kit, media):
    doc = SimpleUploadedFile("Essay plan.docx", b"PK\x03\x04 docx", content_type="text/html")
    lesson_id = post_lesson(auth, kit, doc)["id"]
    r = auth(kit.student).get(f"{LESSONS_URL}{lesson_id}/file/")
    # the type comes from the extension we allow, never from what the uploader claimed
    assert r["Content-Type"].startswith(
        "application/vnd.openxmlformats-officedocument.wordprocessingml"
    )
    assert r["Content-Disposition"].startswith("attachment")


def test_submission_files(auth, kit, media, make_user):
    essay = Assessment.objects.create(
        title="Essay",
        type="assignment",
        classroom=kit.classroom,
        subject=kit.subject,
        term=kit.term,
    )
    r = auth(kit.student).post(
        f"/api/v1/assessments/{essay.pk}/submit/",
        {"file": pdf("My essay.pdf")},
        format="multipart",
    )
    assert r.status_code == 201, r.content
    submission = Submission.objects.get(pk=r.json()["id"])
    assert r.json()["file"].endswith(f"/api/v1/submissions/{submission.pk}/file/")
    assert r.json()["file_name"] == "My essay.pdf"

    url = f"/api/v1/submissions/{submission.pk}/file/"
    parent = make_user("parent")
    Guardianship.objects.create(parent=parent, student=kit.student)
    for reader in (kit.student, kit.teacher, parent):
        assert auth(reader).get(url).status_code == 200, reader.role
    for stranger in (kit.outsider, kit.other_teacher):  # a classmate; a teacher of nothing
        assert auth(stranger).get(url).status_code == 404


def test_no_file_and_no_public_media(auth, kit, media, api):
    lesson = Lesson.objects.create(
        title="Text only", classroom=kit.classroom, subject=kit.subject, term=kit.term
    )
    assert auth(kit.teacher).get(f"{LESSONS_URL}{lesson.pk}/file/").status_code == 404
    data = post_lesson(auth, kit, pdf())
    stored = Lesson.objects.get(pk=data["id"]).file.name
    api.credentials()
    assert api.get(f"/media/{stored}").status_code == 404  # never served directly


def test_replaced_and_deleted_files_are_removed(
    auth, kit, media, django_capture_on_commit_callbacks
):
    with django_capture_on_commit_callbacks(execute=True):
        lesson_id = post_lesson(auth, kit, pdf())["id"]
    first = media / Lesson.objects.get(pk=lesson_id).file.name

    with django_capture_on_commit_callbacks(execute=True):
        r = auth(kit.teacher).patch(
            f"{LESSONS_URL}{lesson_id}/", {"file": pdf("v2.pdf", b"%PDF v2")}, format="multipart"
        )
    assert r.status_code == 200 and r.json()["file_name"] == "v2.pdf"
    second = media / Lesson.objects.get(pk=lesson_id).file.name
    assert not first.exists() and second.exists()

    with django_capture_on_commit_callbacks(execute=True):
        assert auth(kit.teacher).delete(f"{LESSONS_URL}{lesson_id}/").status_code == 204
    assert not second.exists()


def test_s3_style_storage_redirects_to_a_short_lived_link(auth, kit, media, settings, monkeypatch):
    lesson = Lesson.objects.get(pk=post_lesson(auth, kit, pdf())["id"])
    settings.FILES_SERVED_BY_REDIRECT = True
    seen = {}

    def signed_url(name, parameters=None, expire=None):
        seen.update(name=name, parameters=parameters, expire=expire)
        return f"https://bucket.example/{name}?X-Amz-Signature=abc"

    monkeypatch.setattr(lesson.file.storage, "url", signed_url)
    r = auth(kit.student).get(f"{LESSONS_URL}{lesson.pk}/file/")
    assert r.status_code == 302
    assert r["Location"].startswith("https://bucket.example/lessons/")
    assert seen["expire"] == 300 and seen["name"] == lesson.file.name
    assert 'filename="Week 1 Notes.pdf"' in seen["parameters"]["ResponseContentDisposition"]
    assert auth(kit.outsider).get(f"{LESSONS_URL}{lesson.pk}/file/").status_code == 404
