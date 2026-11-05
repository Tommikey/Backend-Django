"""Notifications: who hears about what, in the app and by email, and reading them."""

from datetime import UTC, datetime, timedelta
from unittest import mock

import pytest
from django.core import mail
from django.utils import timezone

from apps.accounts.models import Guardianship
from apps.live_classes.models import LiveClass
from apps.notifications import events, services
from apps.notifications.models import Notification
from conftest import enroll, results

pytestmark = pytest.mark.django_db

URL = "/api/v1/notifications/"
REGISTER_URL = "/api/v1/attendance/register/"


@pytest.fixture
def family(kit, make_user):
    """kit plus a parent of kit.student and a classmate with no email address."""
    kit.parent = make_user("parent")
    Guardianship.objects.create(parent=kit.parent, student=kit.student)
    kit.classmate = make_user("student")
    kit.classmate.email = ""
    kit.classmate.save()
    enroll(kit.classmate, kit.classroom)
    kit.classroom.form_teacher = kit.teacher
    kit.classroom.save()
    return kit


def inbox(user):
    return list(Notification.objects.filter(recipient=user).values_list("kind", "title"))


def to(address):
    return [m for m in mail.outbox if m.to == [address]]


# --- events ----------------------------------------------------------------------------------


def test_publishing_tells_students_and_parents(auth, family, admin_user):
    assert auth(admin_user).post("/api/v1/results/publish/", {}).status_code == 202
    term = family.term.name
    assert inbox(family.student) == [("results_published", f"Your {term} report card is ready")]
    name = family.student.display_name
    assert inbox(family.parent) == [("results_published", f"{name}'s {term} report card is ready")]
    note = Notification.objects.get(recipient=family.parent)
    assert note.data == {"term": family.term.pk, "student": family.student.pk}
    # emailed to those with an address; the classmate has none but still sees it in the app
    assert len(to(family.parent.email)) == 1 and len(to(family.student.email)) == 1
    assert inbox(family.classmate) and note.emailed_at is not None
    assert "Test School on YAP" in to(family.parent.email)[0].body


def test_email_can_be_turned_off(auth, family, admin_user):
    client = auth(family.parent)
    assert client.get(f"{URL}settings/").json() == {"email": True, "has_email": True}
    r = client.patch(f"{URL}settings/", {"email": False}, format="json")
    assert r.json() == {"email": False, "has_email": True}
    auth(admin_user).post("/api/v1/results/publish/", {})
    assert inbox(family.parent) and to(family.parent.email) == []


def take(auth, kit, day, status, student=None):
    body = {
        "classroom": kit.classroom.pk,
        "date": day.isoformat(),
        "marks": [{"student": (student or kit.student).pk, "status": status}],
    }
    r = auth(kit.teacher).put(REGISTER_URL, body, format="json")
    assert r.status_code == 200, r.content


def test_absence_tells_parents_once(auth, family):
    today = family.school.today()
    take(auth, family, today, "absent")
    assert [kind for kind, _ in inbox(family.parent)] == ["absent"]
    note = Notification.objects.get(recipient=family.parent)
    assert note.data["date"] == today.isoformat()
    assert inbox(family.student) == []  # the student isn't told
    take(auth, family, today, "absent")  # saved again: no second alert
    take(auth, family, today, "present")
    assert Notification.objects.filter(recipient=family.parent).count() == 1


def test_late_registers_dont_alert(auth, family):
    take(auth, family, family.school.today() - timedelta(days=3), "absent")
    assert inbox(family.parent) == []
    take(auth, family, family.school.today() - timedelta(days=1), "absent")
    assert len(inbox(family.parent)) == 1  # yesterday's register filled in this morning


def test_new_work_tells_the_class(auth, family):
    due = datetime(2026, 11, 20, 16, 0, tzinfo=UTC)
    payload = {
        "title": "Essay",
        "type": "assignment",
        "classroom": family.classroom.pk,
        "subject": family.subject.pk,
        "due_at": due.isoformat(),
    }
    r = auth(family.teacher).post("/api/v1/assessments/", payload, format="json")
    assert r.status_code == 201, r.content
    assert inbox(family.student) == [("work_set", "New assignment in Mathematics: Essay")]
    note = Notification.objects.get(recipient=family.student)
    assert "due Fri 20 Nov, 17:00" in note.body  # in the school's time zone (Lagos, UTC+1)
    assert inbox(family.outsider) == [] and inbox(family.parent) == []


def make_live(kit, starts_in):
    return LiveClass.objects.create(
        title="Revision",
        classroom=kit.classroom,
        subject=kit.subject,
        term=kit.term,
        hosted_by=kit.teacher,
        starts_at=timezone.now() + starts_in,
        join_url="https://x.example/j",
    )


def test_live_class_reminders(auth, family):
    soon = make_live(family, timedelta(minutes=10))
    later = make_live(family, timedelta(minutes=40))
    assert events.live_class_reminders() == 1
    assert events.live_class_reminders() == 0  # once only
    [(kind, title)] = inbox(family.student)
    at = family.school.local(soon.starts_at).strftime("%H:%M")
    assert (kind, title) == ("live_class_soon", f"Live class at {at}: Revision")
    assert Notification.objects.get(recipient=family.student).data == {"live_class": soon.pk}

    # moved to a new time: reminded again before it
    new_start = timezone.now() + timedelta(minutes=5)
    r = auth(family.teacher).patch(
        f"/api/v1/live-classes/{soon.pk}/", {"starts_at": new_start.isoformat()}, format="json"
    )
    assert r.status_code == 200, r.content
    assert events.live_class_reminders() == 1
    later.refresh_from_db()
    assert later.reminded_at is None


# --- reading them ----------------------------------------------------------------------------


def test_reading_notifications(auth, family, admin_user):
    take(auth, family, family.school.today(), "absent")
    auth(admin_user).post("/api/v1/results/publish/", {})  # locks the register: take it first
    client = auth(family.parent)
    rows = results(client.get(URL).json())
    assert [r["kind"] for r in rows] == ["results_published", "absent"]  # newest first
    assert client.get(f"{URL}unread-count/").json() == {"unread": 2}
    assert client.get("/api/v1/auth/me/").json()["unread_notifications"] == 2

    r = client.post(f"{URL}{rows[0]['id']}/read/")
    assert r.json()["is_read"] is True
    unread = results(client.get(URL, {"unread": "true"}).json())
    assert [r["kind"] for r in unread] == ["absent"]
    assert client.post(f"{URL}read-all/").json() == {"unread": 0}
    assert client.get(f"{URL}unread-count/").json() == {"unread": 0}

    # someone else's notification doesn't exist for you
    other = Notification.objects.filter(recipient=family.student).first()
    assert auth(family.parent).post(f"{URL}{other.pk}/read/").status_code == 404
    assert results(auth(family.teacher).get(URL).json()) == []


def test_a_failed_email_isnt_sent_twice(family, make_user):
    enroll(make_user("student"), family.classroom)  # two students with an address now
    notes = events.work_set(
        family.classroom.assessments.create(
            title="Quiz", type="quiz", subject=family.subject, term=family.term
        )
    )
    expected = sorted(n.recipient.email for n in notes if n.recipient.email)
    assert len(expected) == 2
    Notification.objects.update(emailed_at=None)
    mail.outbox.clear()
    real_send = mail.EmailMessage.send
    calls = {"n": 0}

    def flaky(message, *args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 2:
            raise ConnectionError("smtp down")
        return real_send(message, *args, **kwargs)

    ids = [n.pk for n in notes]
    with mock.patch.object(mail.EmailMessage, "send", flaky):
        with pytest.raises(ConnectionError):
            services.send_emails(ids)
        assert len(mail.outbox) == 1
        services.send_emails(ids)  # the worker's retry
    assert sorted(m.to[0] for m in mail.outbox) == expected  # each exactly once


def test_old_notifications_are_purged(family):
    events.work_set(
        family.classroom.assessments.create(
            title="Quiz", type="quiz", subject=family.subject, term=family.term
        )
    )
    old = timezone.now() - timedelta(days=100)
    Notification.objects.filter(recipient=family.student).update(created_at=old, read_at=old)
    Notification.objects.filter(recipient=family.classmate).update(created_at=old)
    services.purge_old()
    assert inbox(family.student) == []  # read, 100 days old
    assert len(inbox(family.classmate)) == 1  # unread: kept for a year


# --- the school's time zone ------------------------------------------------------------------


def test_school_time_zone(auth, school, admin_user):
    assert school.timezone == "Africa/Lagos"  # from the Nigerian preset
    # 23:30 UTC is already tomorrow in Lagos
    late = datetime(2026, 11, 5, 23, 30, tzinfo=UTC)
    with mock.patch("django.utils.timezone.now", return_value=late):
        assert school.today().isoformat() == "2026-11-06"
    client = auth(admin_user)
    assert client.get("/api/v1/auth/me/").json()["school_details"]["timezone"] == "Africa/Lagos"
    bad = client.patch("/api/v1/schools/me/", {"timezone": "Lagos"}, format="json")
    assert bad.status_code == 400 and "timezone" in bad.json()
    ok = client.patch("/api/v1/schools/me/", {"timezone": "Europe/London"}, format="json")
    assert ok.status_code == 200 and ok.json()["timezone"] == "Europe/London"


def test_scheduled_tasks_are_registered():
    import importlib

    from rq import cron

    import config.cron

    importlib.reload(config.cron)
    names = {job["func"].__name__ for job in cron._job_data_registry}
    assert names == {"send_live_class_reminders", "purge_old_notifications"}
