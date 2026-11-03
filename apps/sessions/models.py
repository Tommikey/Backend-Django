from django.conf import settings
from django.db import models

from apps.academics.models import Classroom, Subject


class StudySession(models.Model):
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    classroom = models.ForeignKey(
        Classroom, on_delete=models.CASCADE, related_name="study_sessions"
    )
    # shortcut: subject optional, general sessions have none
    subject = models.ForeignKey(
        Subject, null=True, blank=True, on_delete=models.PROTECT, related_name="study_sessions"
    )
    hosted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        on_delete=models.SET_NULL,
        related_name="sessions_hosted",
    )
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField(null=True, blank=True)
    join_url = models.URLField()
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.title} @ {self.starts_at:%Y-%m-%d %H:%M}"
