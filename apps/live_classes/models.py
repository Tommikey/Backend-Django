from django.conf import settings
from django.db import models

from apps.academics.models import Classroom, Subject, Term


class LiveClass(models.Model):
    """A scheduled online class for one class arm and subject, e.g. a revision call."""

    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    classroom = models.ForeignKey(
        Classroom, on_delete=models.CASCADE, related_name="live_classes"
    )
    # required: the subject's teaching assignment decides who may host it
    subject = models.ForeignKey(Subject, on_delete=models.PROTECT, related_name="live_classes")
    term = models.ForeignKey(Term, on_delete=models.PROTECT, related_name="live_classes")
    hosted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        on_delete=models.SET_NULL,
        related_name="live_classes_hosted",
    )
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField(null=True, blank=True)
    join_url = models.URLField()
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.title} @ {self.starts_at:%Y-%m-%d %H:%M}"
