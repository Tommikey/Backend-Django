import uuid
from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone

# a queued or running job older than this is assumed lost (worker stopped, Redis wiped):
# it no longer blocks starting the same work again
STALE_AFTER = timedelta(minutes=15)


class JobQuerySet(models.QuerySet):
    def active(self):
        return self.filter(
            status__in=[Job.Status.QUEUED, Job.Status.RUNNING],
            created_at__gte=timezone.now() - STALE_AFTER,
        )


class Job(models.Model):
    """Work that runs outside the request (see jobs/queue.py), with a status to poll."""

    class Kind(models.TextChoices):
        PUBLISH_RESULTS = "publish_results", "Publish results"

    class Status(models.TextChoices):
        QUEUED = "queued"
        RUNNING = "running"
        DONE = "done"
        FAILED = "failed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    school = models.ForeignKey("schools.School", on_delete=models.CASCADE, related_name="jobs")
    kind = models.CharField(max_length=40, choices=Kind.choices)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.QUEUED)
    params = models.JSONField(default=dict, blank=True)
    result = models.JSONField(null=True, blank=True)
    error = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    objects = JobQuerySet.as_manager()

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["school", "kind", "status"])]

    def __str__(self):
        return f"{self.get_kind_display()} ({self.status})"
