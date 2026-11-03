from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    class Role(models.TextChoices):
        STUDENT = "student", "Student"
        TEACHER = "teacher", "Teacher"
        ADMIN = "admin", "Admin"

    role = models.CharField(max_length=10, choices=Role.choices, default=Role.STUDENT)

    # shortcut: superusers are always admins, keeps the role invariant in one place
    def save(self, *args, **kwargs):
        if self.is_superuser:
            self.role = self.Role.ADMIN
        super().save(*args, **kwargs)
