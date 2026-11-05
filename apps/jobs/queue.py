"""Running work outside the request.

With ``REDIS_URL`` set, work is queued in Redis (django-rq) once the current transaction commits
and a worker runs it (``manage.py rqworker default --with-scheduler``). Without it (development,
tests) the same work runs straight away, inside the request, so nothing else is needed to run
the app.

- ``run_later(func, *args)``: fire and forget (emails). Retried by the worker if it raises.
- ``start(kind, school, user, **params)``: a tracked ``Job`` whose status the client polls.
"""

import logging

import django_rq
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from django.utils.module_loading import import_string
from rq import Retry

from .models import Job

logger = logging.getLogger(__name__)

# what runs each kind of job: a function taking the Job and returning its result (JSON)
TASKS = {
    Job.Kind.PUBLISH_RESULTS: "apps.results.jobs.publish_results",
}
JOB_TIMEOUT = 600  # seconds; a job still running after this is stopped by the worker
EMAIL_RETRY = Retry(max=3, interval=[60, 300, 900])
UNAVAILABLE = "Background work is unavailable right now. Try again in a few minutes."


class JobRefused(Exception):
    """Raised by a task when the work can't be done; the message is shown to the user."""


def queue():
    return django_rq.get_queue("default")


def run_later(func, *args, retry=None, **kwargs):
    if not settings.JOBS_ASYNC:
        try:
            func(*args, **kwargs)
        except Exception:  # fire and forget: never fail the request that asked for it
            logger.exception("%s failed", func.__name__)
        return
    # the description is what worker logs show: the function only, never its arguments (a
    # login typed into the reset form may be an email address)
    description = f"{func.__module__}.{func.__qualname__}"

    def send():
        try:
            queue().enqueue(
                func, *args, retry=retry, job_timeout=JOB_TIMEOUT, description=description, **kwargs
            )
        except Exception:  # Redis down: the request still succeeds; staff see the log
            logger.exception("could not queue %s", description)

    transaction.on_commit(send)


def start(kind, school, user, **params):
    job = Job.objects.create(kind=kind, school=school, created_by=user, params=params)
    if settings.JOBS_ASYNC:
        transaction.on_commit(lambda: _send(job))
    else:
        run(job.pk)
        job.refresh_from_db()
    return job


def _send(job):
    try:
        queue().enqueue(run, job.pk, job_id=str(job.pk), job_timeout=JOB_TIMEOUT)
    except Exception:  # Redis down: fail the job now rather than leave it queued forever
        logger.exception("could not queue job %s", job.pk)
        Job.objects.filter(pk=job.pk, status=Job.Status.QUEUED).update(
            status=Job.Status.FAILED, error=UNAVAILABLE, finished_at=timezone.now()
        )


def run(job_id):
    """The worker's entry point for a tracked job. Safe to call twice: only a queued job runs."""
    claimed = Job.objects.filter(pk=job_id, status=Job.Status.QUEUED).update(
        status=Job.Status.RUNNING, started_at=timezone.now()
    )
    if not claimed:
        return
    job = Job.objects.select_related("school", "created_by").get(pk=job_id)
    try:
        with transaction.atomic():  # all or nothing
            job.result = import_string(TASKS[job.kind])(job)
        job.status = Job.Status.DONE
    except JobRefused as refused:
        job.status, job.error = Job.Status.FAILED, str(refused)
    except Exception:
        logger.exception("job %s (%s) failed", job.pk, job.kind)
        job.status = Job.Status.FAILED
        job.error = "Something went wrong. Try again; if it keeps failing, contact support."
    job.finished_at = timezone.now()
    job.save(update_fields=["status", "result", "error", "finished_at"])
