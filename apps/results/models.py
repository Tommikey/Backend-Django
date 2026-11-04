"""Term results: raw scores entered by teachers, and the report-card snapshot taken when the
admin publishes a term.

Scores stay editable until the term is published. Publishing computes totals, grades,
averages, positions / GPA and stores them (TermResult + SubjectResult), so a published report
card never changes when the grade scale or a subject is edited later.
"""

from django.conf import settings
from django.db import models


class Score(models.Model):
    """One student's mark for one component (CA1, Exam...) of one subject in one term."""

    student = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="scores"
    )
    subject = models.ForeignKey(
        "academics.Subject", on_delete=models.PROTECT, related_name="scores"
    )
    # PROTECT (here and below): deleting a subject, term, session or class must never wipe
    # marks or report cards; the API turns the refusal into a 409
    term = models.ForeignKey("academics.Term", on_delete=models.PROTECT, related_name="scores")
    # PROTECT: replacing the score split must not silently delete entered marks
    component = models.ForeignKey(
        "schools.AssessmentComponent", on_delete=models.PROTECT, related_name="scores"
    )
    value = models.DecimalField(max_digits=5, decimal_places=2)
    entered_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+"
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["student", "subject", "term", "component"], name="one_score_per_component"
            )
        ]

    def __str__(self):
        return f"{self.student} {self.subject} {self.component}: {self.value}"


class Publication(models.Model):
    """A term whose results are published: report cards visible, scores locked."""

    term = models.OneToOneField(
        "academics.Term", on_delete=models.PROTECT, related_name="publication"
    )
    published_at = models.DateTimeField(auto_now_add=True)
    published_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+"
    )
    # the grade scale and display options in force when published, printed on report cards
    grading_scale = models.JSONField(default=list)
    show_position = models.BooleanField(default=False)
    use_gpa = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.term} published"


class TermResult(models.Model):
    """A student's report card for a term. Comments can be written before publishing; the
    computed fields are filled in at publish time and cleared if the term is unpublished.
    """

    student = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="term_results"
    )
    term = models.ForeignKey("academics.Term", on_delete=models.PROTECT, related_name="results")
    classroom = models.ForeignKey(
        "academics.Classroom", on_delete=models.PROTECT, related_name="term_results"
    )
    # computed at publish
    total = models.DecimalField(max_digits=7, decimal_places=2, null=True, blank=True)
    average = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    subjects_count = models.PositiveSmallIntegerField(default=0)
    position = models.PositiveSmallIntegerField(null=True, blank=True)
    out_of = models.PositiveSmallIntegerField(null=True, blank=True)
    gpa = models.DecimalField(max_digits=3, decimal_places=2, null=True, blank=True)
    form_teacher_name = models.CharField(max_length=150, blank=True)
    # written by people
    form_teacher_comment = models.TextField(blank=True)
    principal_comment = models.TextField(blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["student", "term"], name="one_result_per_term"),
        ]

    def __str__(self):
        return f"{self.student} {self.term}"


class SubjectResult(models.Model):
    """One subject line of a published report card (a snapshot; names are copied)."""

    term_result = models.ForeignKey(
        TermResult, on_delete=models.CASCADE, related_name="subject_results"
    )
    subject = models.ForeignKey(
        "academics.Subject", null=True, on_delete=models.SET_NULL, related_name="+"
    )
    subject_name = models.CharField(max_length=100)
    # [{"component": "CA1", "max_score": 20, "value": "15.00" | null}, ...]
    scores = models.JSONField(default=list)
    total = models.DecimalField(max_digits=5, decimal_places=2)
    grade = models.CharField(max_length=10)
    remark = models.CharField(max_length=50, blank=True)
    grade_point = models.DecimalField(max_digits=3, decimal_places=2, null=True, blank=True)
    class_average = models.DecimalField(max_digits=5, decimal_places=2)
    class_highest = models.DecimalField(max_digits=5, decimal_places=2)
    class_lowest = models.DecimalField(max_digits=5, decimal_places=2)
    position = models.PositiveSmallIntegerField(null=True, blank=True)

    class Meta:
        ordering = ["subject_name"]

    def __str__(self):
        return f"{self.term_result} {self.subject_name}: {self.total} {self.grade}"
