from datetime import timedelta

import pytest
from django.utils import timezone

from apps.live_classes.models import LiveClass
from conftest import results

pytestmark = pytest.mark.django_db

URL = "/api/v1/live-classes/"


def payload(kit, **overrides):
    return {
        "title": "Algebra revision",
        "classroom": kit.classroom.pk,
        "subject": kit.subject.pk,
        "starts_at": (timezone.now() + timedelta(days=1)).isoformat(),
        "join_url": "https://meet.jit.si/yap-algebra",
        **overrides,
    }


def make_live_class(kit, title="S", starts_in=timedelta(days=1)):
    return LiveClass.objects.create(
        title=title,
        classroom=kit.classroom,
        subject=kit.subject,
        term=kit.term,
        hosted_by=kit.teacher,
        starts_at=timezone.now() + starts_in,
        join_url="https://x.example/j",
    )


def test_subject_teacher_schedules_live_class(auth, kit):
    r = auth(kit.teacher).post(URL, payload(kit))
    assert r.status_code == 201, r.content
    live = LiveClass.objects.get(pk=r.data["id"])
    assert live.hosted_by == kit.teacher and live.term == kit.term


def test_subject_is_required(auth, kit):
    r = auth(kit.teacher).post(URL, payload(kit, subject=""))
    assert r.status_code == 400 and "subject" in r.json()


def test_other_teachers_cannot_schedule_or_edit(auth, kit):
    assert auth(kit.other_teacher).post(URL, payload(kit)).status_code == 403
    live = make_live_class(kit)
    assert auth(kit.other_teacher).patch(f"{URL}{live.pk}/", {"title": "X"}).status_code == 403


def test_student_sees_only_their_class(auth, kit):
    make_live_class(kit)
    assert len(results(auth(kit.student).get(URL).json())) == 1
    assert results(auth(kit.outsider).get(URL).json()) == []
    assert len(results(auth(kit.teacher).get(URL).json())) == 1


def test_student_cannot_schedule(auth, kit):
    assert auth(kit.student).post(URL, payload(kit)).status_code == 403


def test_upcoming_filter(auth, kit):
    make_live_class(kit, "Past", starts_in=timedelta(days=-1))
    make_live_class(kit, "Future")
    upcoming = results(auth(kit.student).get(f"{URL}?upcoming=1").json())
    assert [s["title"] for s in upcoming] == ["Future"]
