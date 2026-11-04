"""The daily class register: one mark per student per school day, taken by the form teacher.

A day counts as a day the school opened for a class once that class's register has been
taken for it (at least one student marked). Late counts as present; excused counts as absent
but is reported separately, as report cards usually do.
"""

from django.conf import settings
from django.db import models


class AttendanceRecord(models.Model):
    class Status(models.TextChoices):
        PRESENT = "present", "Present"
        LATE = "late", "Late"
        ABSENT = "absent", "Absent"
        EXCUSED = "excused", "Excused absence"

    school_path = "classroom__school"  # see SameSchoolSerializerMixin

    student = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="attendance_records"
    )
    # PROTECT: deleting a class or term must never wipe the register (the API answers 409)
    classroom = models.ForeignKey(
        "academics.Classroom", on_delete=models.PROTECT, related_name="attendance_records"
    )
    term = models.ForeignKey(
        "academics.Term", on_delete=models.PROTECT, related_name="attendance_records"
    )
    date = models.DateField()
    status = models.CharField(max_length=10, choices=Status.choices)
    note = models.CharField(max_length=200, blank=True)  # e.g. "Hospital appointment"
    marked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+"
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["date"]
        constraints = [
            models.UniqueConstraint(fields=["student", "date"], name="one_mark_per_student_per_day")
        ]
        indexes = [models.Index(fields=["classroom", "term", "date"])]

    def __str__(self):
        return f"{self.student} {self.date}: {self.status}"
