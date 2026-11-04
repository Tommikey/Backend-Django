"""A school (tenant) and its configuration.

Everything that differs between the Nigerian, British and US systems is data on these models,
filled in from a preset at onboarding (see presets.py) and editable by the school's admin.
"""

from django.db import models


class School(models.Model):
    class System(models.TextChoices):
        NG = "ng", "Nigerian (JSS/SSS)"
        UK = "uk", "British (Year 7-13)"
        US = "us", "US (Grade 6-12)"

    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=80, unique=True)
    system = models.CharField(max_length=2, choices=System.choices)
    # report-card display options; defaults come from the preset
    show_position = models.BooleanField(default=False)
    use_gpa = models.BooleanField(default=False)
    # names of the terms in one academic session, in order, e.g. ["First Term", ...]
    term_labels = models.JSONField(default=list)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class Level(models.Model):
    """A year group: JSS1, Year 7, Grade 6..."""

    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name="levels")
    name = models.CharField(max_length=50)
    order = models.PositiveSmallIntegerField()

    class Meta:
        ordering = ["order"]
        constraints = [
            models.UniqueConstraint(fields=["school", "name"], name="unique_school_level_name"),
        ]

    def __str__(self):
        return self.name


class AssessmentComponent(models.Model):
    """One part of a subject's term score, e.g. CA1 (20) or Exam (60). Maxima sum to 100."""

    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name="components")
    name = models.CharField(max_length=50)
    max_score = models.PositiveSmallIntegerField()
    order = models.PositiveSmallIntegerField()

    class Meta:
        ordering = ["order"]
        constraints = [
            models.UniqueConstraint(fields=["school", "name"], name="unique_school_component"),
        ]

    def __str__(self):
        return f"{self.name} ({self.max_score})"


class GradeBand(models.Model):
    """A grade awarded for totals at or above ``min_score`` (up to the next band).

    Storing only the lower bound means bands can never overlap or leave gaps.
    """

    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name="grade_bands")
    label = models.CharField(max_length=10)
    min_score = models.DecimalField(max_digits=5, decimal_places=2)
    remark = models.CharField(max_length=50, blank=True)
    grade_point = models.DecimalField(max_digits=3, decimal_places=2, null=True, blank=True)

    class Meta:
        ordering = ["-min_score"]
        constraints = [
            models.UniqueConstraint(fields=["school", "label"], name="unique_school_grade_label"),
            models.UniqueConstraint(fields=["school", "min_score"], name="unique_school_grade_min"),
        ]

    def __str__(self):
        return f"{self.label} (>= {self.min_score})"
