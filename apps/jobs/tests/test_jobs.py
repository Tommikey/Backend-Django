"""Background jobs: publishing runs as a tracked job, reset emails are queued.

Without Redis (the test default) jobs run inside the request; with it they are queued after
the transaction commits and a worker runs them. The queued path runs here against fakeredis
with a real RQ worker.
"""

from datetime import timedelta

import fakeredis
import pytest
from django.core import mail
from django.utils import timezone
from rq import Queue, SimpleWorker

from apps.jobs import queue as jobs
from apps.jobs.models import Job
from apps.results.models import Publication
from conftest import PASSWORD

pytestmark = pytest.mark.django_db

PUBLISH_URL = "/api/v1/results/publish/"


@pytest.fixture
def redis_queue(settings, monkeypatch):
    """Queue jobs in a fake Redis, as production does; ``work()`` runs them like a worker."""
    settings.JOBS_ASYNC = True
    connection = fakeredis.FakeStrictRedis()
    q = Queue("default", connection=connection)
    monkeypatch.setattr(jobs, "queue", lambda: q)

    def work():
        SimpleWorker([q], connection=connection).work(burst=True)

    q.work = work
    return q


def test_publish_runs_as_a_job(auth, kit, admin_user):
    r = auth(admin_user).post(PUBLISH_URL, {})
    assert r.status_code == 202, r.content
    job = r.json()
    assert job["status"] == "done" and job["result"]["report_cards"] == 1
    assert r["Location"] == job["url"]
    polled = auth(admin_user).get(job["url"]).json()
    assert polled["status"] == "done" and polled["finished_at"]
    assert Publication.objects.filter(term=kit.term).exists()


def test_publish_through_the_queue(
    auth, kit, admin_user, redis_queue, django_capture_on_commit_callbacks
):
    with django_capture_on_commit_callbacks(execute=True):
        r = auth(admin_user).post(PUBLISH_URL, {})
    assert r.status_code == 202
    job = r.json()
    assert job["status"] == "queued" and job["result"] is None
    assert redis_queue.job_ids == [job["id"]]
    assert not Publication.objects.filter(term=kit.term).exists()
    # while it waits, nobody can start publishing the same term again
    assert auth(admin_user).post(PUBLISH_URL, {}).status_code == 409

    redis_queue.work()
    polled = auth(admin_user).get(job["url"]).json()
    assert polled["status"] == "done", polled
    assert polled["result"]["report_cards"] == 1
    assert Publication.objects.filter(term=kit.term).exists()


def test_lost_jobs_stop_blocking(auth, kit, admin_user):
    stuck = Job.objects.create(
        kind=Job.Kind.PUBLISH_RESULTS,
        school=kit.school,
        status=Job.Status.RUNNING,
        params={"term": kit.term.pk},
    )
    assert auth(admin_user).post(PUBLISH_URL, {}).status_code == 409
    Job.objects.filter(pk=stuck.pk).update(created_at=timezone.now() - timedelta(hours=1))
    assert auth(admin_user).post(PUBLISH_URL, {}).status_code == 202


def test_a_job_runs_once(kit, admin_user):
    job = jobs.start(Job.Kind.PUBLISH_RESULTS, kit.school, admin_user, term=kit.term.pk)
    finished = job.finished_at
    jobs.run(job.pk)  # delivered twice: the second run does nothing
    job.refresh_from_db()
    assert job.status == "done" and job.finished_at == finished


def test_refused_and_failed_jobs(kit, admin_user, monkeypatch):
    jobs.start(Job.Kind.PUBLISH_RESULTS, kit.school, admin_user, term=kit.term.pk)
    # the term got published another way before this job ran
    again = jobs.start(Job.Kind.PUBLISH_RESULTS, kit.school, admin_user, term=kit.term.pk)
    assert (again.status, again.error) == ("failed", "This term is already published.")

    Publication.objects.all().delete()

    def half_done(term, user):
        Publication.objects.create(term=term, published_by=user)
        raise RuntimeError("database fell over")

    monkeypatch.setattr("apps.results.jobs.publish_term", half_done)
    broken = jobs.start(Job.Kind.PUBLISH_RESULTS, kit.school, admin_user, term=kit.term.pk)
    assert broken.status == "failed" and "Try again" in broken.error
    assert "database" not in broken.error  # no internals shown to users
    assert not Publication.objects.exists()  # all or nothing


def test_who_sees_which_jobs(auth, kit, admin_user, make_user, other_school):
    job = auth(admin_user).post(PUBLISH_URL, {}).json()
    url = f"/api/v1/jobs/{job['id']}/"
    assert auth(admin_user).get(url).status_code == 200
    for outsider in (kit.teacher, make_user("admin", school=other_school)):
        assert auth(outsider).get(url).status_code == 404
        assert auth(outsider).get("/api/v1/jobs/").json()["results"] == []
    listed = auth(admin_user).get("/api/v1/jobs/", {"kind": "publish_results", "status": "done"})
    assert [j["id"] for j in listed.json()["results"]] == [job["id"]]
    assert auth(admin_user).get("/api/v1/jobs/", {"status": "failed"}).json()["results"] == []
    assert auth(admin_user).post("/api/v1/jobs/", {}).status_code == 405


def test_reset_emails_go_through_the_queue(
    api, make_user, redis_queue, django_capture_on_commit_callbacks
):
    teacher = make_user("teacher")
    api.credentials()
    for login in (teacher.username, "nobody-here"):
        with django_capture_on_commit_callbacks(execute=True):
            assert api.post("/api/v1/auth/password-reset/", {"login": login}).status_code == 200
    assert mail.outbox == []  # nothing is looked up or sent inside the request
    assert len(redis_queue.job_ids) == 2

    with django_capture_on_commit_callbacks(execute=True):
        redis_queue.work()  # finds the account and queues its email
    redis_queue.work()  # sends it
    assert [m.to for m in mail.outbox] == [[teacher.email]]


def test_failed_emails_are_retried(
    make_user, redis_queue, monkeypatch, django_capture_on_commit_callbacks
):
    from apps.accounts import password_reset

    teacher = make_user("teacher")

    def down(*args, **kwargs):
        raise ConnectionRefusedError("smtp down")

    monkeypatch.setattr(password_reset, "send_mail", down)
    with django_capture_on_commit_callbacks(execute=True):
        password_reset.send_reset_emails(teacher.username)
    queued = redis_queue.fetch_job(redis_queue.job_ids[0])
    redis_queue.work()
    queued.refresh()
    assert queued.retries_left == 2  # will try again later (the worker's scheduler)


def test_health_check_reports_redis_without_failing(api, settings, monkeypatch):
    import django_rq

    settings.JOBS_ASYNC = True

    def unreachable(name):
        raise ConnectionError("no redis")

    monkeypatch.setattr(django_rq, "get_connection", unreachable)
    r = api.get("/healthz/")
    # every app server shares Redis: failing the check would take them all out of rotation
    assert r.status_code == 200
    assert r.json() == {"status": "degraded", "redis": "unreachable"}


def test_publish_when_redis_is_down(
    auth, kit, admin_user, settings, monkeypatch, django_capture_on_commit_callbacks
):
    settings.JOBS_ASYNC = True

    def down():
        raise ConnectionError("no redis")

    monkeypatch.setattr(jobs, "queue", down)
    with django_capture_on_commit_callbacks(execute=True):
        r = auth(admin_user).post(PUBLISH_URL, {})
    assert r.status_code == 202
    job = auth(admin_user).get(r["Location"]).json()
    assert job["status"] == "failed" and "unavailable" in job["error"]
    # nothing is left blocking a retry once Redis is back
    monkeypatch.undo()
    assert auth(admin_user).post(PUBLISH_URL, {}).status_code == 202


def test_rate_limits_pause_when_the_cache_is_down(api, admin_user, settings):
    from django.core.cache import caches

    settings.CACHES = {
        "default": {
            "BACKEND": "config.cache.ForgivingRedisCache",
            "LOCATION": "redis://127.0.0.1:1/0",  # nothing listens here
            "OPTIONS": {"socket_connect_timeout": 0.2, "socket_timeout": 0.2},
        }
    }
    cache = caches["default"]
    assert cache.get("missing", "fallback") == "fallback"
    assert cache.add("k", 1) is False and cache.get_many(["k"]) == {}
    api.credentials()
    r = api.post("/api/v1/auth/token/", {"username": "admin", "password": PASSWORD})
    assert r.status_code == 200, r.content


def test_worker_health_check(monkeypatch):
    import django_rq
    from django.core.management import CommandError, call_command
    from rq import Worker

    connection = fakeredis.FakeStrictRedis()
    monkeypatch.setattr(django_rq, "get_connection", lambda name: connection)
    with pytest.raises(CommandError, match="no live worker"):
        call_command("workerhealth")
    Worker([Queue("default", connection=connection)], connection=connection).register_birth()
    call_command("workerhealth")
