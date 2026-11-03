from django.conf import settings
from django.db import models


class Subject(models.Model):
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True)

    def __str__(self):
        return self.name


class Classroom(models.Model):
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        on_delete=models.SET_NULL,
        related_name="classrooms_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class Enrollment(models.Model):
    classroom = models.ForeignKey(Classroom, on_delete=models.CASCADE, related_name="enrollments")
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="enrollments"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["classroom", "student"], name="unique_classroom_student"
            )
        ]

    def __str__(self):
        return f"{self.student} @ {self.classroom}"


class Lesson(models.Model):
    title = models.CharField(max_length=200)
    content = models.TextField(blank=True)
    file = models.FileField(upload_to="lessons/%Y/%m/", blank=True)
    classroom = models.ForeignKey(Classroom, on_delete=models.CASCADE, related_name="lessons")
    subject = models.ForeignKey(Subject, on_delete=models.PROTECT, related_name="lessons")
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
