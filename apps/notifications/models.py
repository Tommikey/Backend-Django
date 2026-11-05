from django.conf import settings
from django.db import models


class Notification(models.Model):
    """Something one person should know about. Shown in the app; also emailed to people
    with an email address who haven't turned email notifications off."""

    class Kind(models.TextChoices):
        RESULTS_PUBLISHED = "results_published", "Report card ready"
        ABSENT = "absent", "Marked absent"
        WORK_SET = "work_set", "New quiz or assignment"
        LIVE_CLASS_SOON = "live_class_soon", "Live class starting soon"

    school = models.ForeignKey(
        "schools.School", on_delete=models.CASCADE, related_name="notifications"
    )
    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications"
    )
    kind = models.CharField(max_length=30, choices=Kind.choices)
    title = models.CharField(max_length=200)
    body = models.TextField()
    # ids a client needs to open the thing, e.g. {"term": 3, "student": 12}
    data = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    read_at = models.DateTimeField(null=True, blank=True)
    emailed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["recipient", "read_at"]),
            models.Index(fields=["created_at"]),
        ]

    def __str__(self):
        return self.title
