from django.db import models

DAYS = {1: "Monday", 2: "Tuesday", 3: "Wednesday", 4: "Thursday", 5: "Friday", 6: "Saturday"}
SCHOOL_WEEK = (1, 2, 3, 4, 5)  # always shown; Saturday only when something is on it


class Period(models.Model):
    """One part of the school day, the same every day: "Period 1, 08:00-08:40", or a break."""

    school = models.ForeignKey("schools.School", on_delete=models.CASCADE, related_name="periods")
    name = models.CharField(max_length=50)
    starts_at = models.TimeField()
    ends_at = models.TimeField()
    # breaks (assembly, lunch) show on the timetable but nothing is taught in them
    is_break = models.BooleanField(default=False)

    class Meta:
        ordering = ["starts_at"]
        constraints = [
            models.UniqueConstraint(fields=["school", "name"], name="unique_school_period_name"),
            models.CheckConstraint(
                condition=models.Q(ends_at__gt=models.F("starts_at")),
                name="period_ends_after_start",
            ),
        ]

    def __str__(self):
        return f"{self.name} ({self.starts_at:%H:%M}-{self.ends_at:%H:%M})"


class Slot(models.Model):
    """One lesson in a class's week: this subject (and its teacher), this day, this period.

    It points at the teaching assignment, so a class can only be timetabled for what it is
    taught, and the teacher follows the assignment. ``classroom`` and ``session`` are copies
    of the assignment's, kept so the database can refuse two lessons in one class's period.
    """

    assignment = models.ForeignKey(
        "academics.TeachingAssignment", on_delete=models.CASCADE, related_name="slots"
    )
    session = models.ForeignKey(
        "academics.AcademicSession", on_delete=models.CASCADE, related_name="+"
    )
    classroom = models.ForeignKey("academics.Classroom", on_delete=models.CASCADE, related_name="+")
    day = models.PositiveSmallIntegerField(choices=list(DAYS.items()))
    period = models.ForeignKey(Period, on_delete=models.PROTECT, related_name="slots")

    class Meta:
        ordering = ["day", "period__starts_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["session", "classroom", "day", "period"], name="one_lesson_per_class_period"
            ),
        ]

    def __str__(self):
        return f"{self.classroom} {DAYS[self.day]} {self.period.name}"

    def save(self, *args, **kwargs):
        self.session_id = self.assignment.session_id
        self.classroom_id = self.assignment.classroom_id
        super().save(*args, **kwargs)
