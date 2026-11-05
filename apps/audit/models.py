from django.conf import settings
from django.db import models


class AuditEntry(models.Model):
    """One change to records that matter (marks, attendance, people, results), kept for good.

    Entries are only ever added: the API and the Django admin can't edit or delete them. The
    actor's name is copied in, so an entry still reads correctly if the account goes.
    """

    school = models.ForeignKey(
        "schools.School", on_delete=models.CASCADE, related_name="audit_entries"
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+"
    )
    actor_name = models.CharField(max_length=300, blank=True)
    action = models.CharField(max_length=60)  # e.g. "scores.updated", "user.deleted"
    target_type = models.CharField(max_length=40, blank=True)  # e.g. "user", "term"
    target_id = models.BigIntegerField(null=True, blank=True)
    target_label = models.CharField(max_length=300, blank=True)
    # {field: [old, new]} for one record, or a list of per-student rows for a sheet
    changes = models.JSONField(default=dict, blank=True)
    # ids and names of what it happened in: classroom, subject, term, date...
    context = models.JSONField(default=dict, blank=True)
    ip = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        verbose_name_plural = "audit entries"
        indexes = [
            models.Index(fields=["school", "-created_at"]),
            models.Index(fields=["school", "action"]),
            models.Index(fields=["target_type", "target_id"]),
        ]

    def __str__(self):
        return f"{self.actor_name or 'system'}: {self.action} {self.target_label}"
