"""How a school's year is organised: sessions and terms, classes, subjects, who teaches what,
and which class each student is in. Lessons hang off a class, subject and term.
"""

from django.conf import settings
from django.db import models


class AcademicSession(models.Model):
    """A school year, e.g. 2025/2026. Its terms are created with it from the school's term names."""

    school = models.ForeignKey(
        "schools.School", on_delete=models.CASCADE, related_name="academic_sessions"
    )
    name = models.CharField(max_length=20)
    starts_on = models.DateField(null=True, blank=True)
    ends_on = models.DateField(null=True, blank=True)
    is_current = models.BooleanField(default=False)

    class Meta:
        ordering = ["-starts_on", "-name"]
        constraints = [
            models.UniqueConstraint(fields=["school", "name"], name="unique_school_session"),
        ]

    def __str__(self):
        return self.name


class Term(models.Model):
    """A term or semester within a session. The school has at most one current term."""

    school_path = "session__school"  # see SameSchoolSerializerMixin

    session = models.ForeignKey(AcademicSession, on_delete=models.CASCADE, related_name="terms")
    name = models.CharField(max_length=50)
    order = models.PositiveSmallIntegerField()
    starts_on = models.DateField(null=True, blank=True)
    ends_on = models.DateField(null=True, blank=True)
    is_current = models.BooleanField(default=False)

    class Meta:
        ordering = ["session", "order"]
        constraints = [
            models.UniqueConstraint(fields=["session", "order"], name="unique_session_term"),
        ]

    def __str__(self):
        return f"{self.name} {self.session}"


class Subject(models.Model):
    school = models.ForeignKey("schools.School", on_delete=models.CASCADE, related_name="subjects")
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(fields=["school", "name"], name="unique_school_subject"),
        ]

    def __str__(self):
        return self.name


class Classroom(models.Model):
    """A class arm, e.g. JSS2A (level JSS2, arm A). It persists across sessions; who is in it
    and who teaches it are recorded per session (Enrollment, TeachingAssignment).
    """

    school = models.ForeignKey(
        "schools.School", on_delete=models.CASCADE, related_name="classrooms"
    )
    level = models.ForeignKey("schools.Level", on_delete=models.PROTECT, related_name="classrooms")
    arm = models.CharField(max_length=20, blank=True)  # "A", "Gold"... blank for a single arm
    # shortcut: the current form teacher only; history lives on published report cards
    form_teacher = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="form_classes",
    )
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["level__order", "arm"]
        constraints = [
            models.UniqueConstraint(fields=["level", "arm"], name="unique_level_arm"),
        ]

    def __str__(self):
        return self.name

    @property
    def name(self):
        return f"{self.level.name}{self.arm}"


class TeachingAssignment(models.Model):
    """"This teacher teaches this subject to this class this session." The basis of what
    teachers may post and grade.
    """

    session = models.ForeignKey(
        AcademicSession, on_delete=models.CASCADE, related_name="teaching_assignments"
    )
    classroom = models.ForeignKey(
        Classroom, on_delete=models.CASCADE, related_name="teaching_assignments"
    )
    subject = models.ForeignKey(
        Subject, on_delete=models.CASCADE, related_name="teaching_assignments"
    )
    teacher = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="teaching_assignments"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            # one teacher per subject per class per session
            models.UniqueConstraint(
                fields=["session", "classroom", "subject"], name="unique_class_subject_session"
            ),
        ]

    def __str__(self):
        return f"{self.teacher} teaches {self.subject} to {self.classroom} ({self.session})"


class Enrollment(models.Model):
    """A student's class for one session."""

    session = models.ForeignKey(
        AcademicSession, on_delete=models.CASCADE, related_name="enrollments"
    )
    classroom = models.ForeignKey(Classroom, on_delete=models.CASCADE, related_name="enrollments")
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="enrollments"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["session", "student"], name="one_class_per_student_per_session"
            )
        ]

    def __str__(self):
        return f"{self.student} @ {self.classroom} ({self.session})"


class Lesson(models.Model):
    title = models.CharField(max_length=200)
    content = models.TextField(blank=True)
    file = models.FileField(upload_to="lessons/%Y/%m/", blank=True)
    classroom = models.ForeignKey(Classroom, on_delete=models.CASCADE, related_name="lessons")
    subject = models.ForeignKey(Subject, on_delete=models.PROTECT, related_name="lessons")
    term = models.ForeignKey(Term, on_delete=models.PROTECT, related_name="lessons")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        on_delete=models.SET_NULL,
        related_name="lessons_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.title


class Completion(models.Model):
    lesson = models.ForeignKey(Lesson, on_delete=models.CASCADE, related_name="completions")
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="completions"
    )
    completed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["lesson", "student"], name="unique_lesson_student")
        ]

    def __str__(self):
        return f"{self.student} completed {self.lesson}"
