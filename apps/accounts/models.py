from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models.functions import Upper


class User(AbstractUser):
    class Role(models.TextChoices):
        STUDENT = "student", "Student"
        TEACHER = "teacher", "Teacher"
        PARENT = "parent", "Parent"
        ADMIN = "admin", "Admin"

    role = models.CharField(max_length=10, choices=Role.choices, default=Role.STUDENT)
    # every user belongs to one school; only platform staff (superusers) have none
    school = models.ForeignKey(
        "schools.School", null=True, blank=True, on_delete=models.CASCADE, related_name="users"
    )
    # the school's own number for a student, e.g. DSS/2025/014; unique in the school (any case)
    admission_number = models.CharField(max_length=30, blank=True, default="")

    class Meta(AbstractUser.Meta):
        constraints = [
            models.UniqueConstraint(
                Upper("admission_number"),
                "school",
                condition=~models.Q(admission_number=""),
                name="unique_admission_number_in_school",
            )
        ]

    @property
    def display_name(self):
        return self.get_full_name() or self.username

    # shortcut: superusers are always admins, keeps the role invariant in one place
    def save(self, *args, **kwargs):
        if self.is_superuser:
            self.role = self.Role.ADMIN
        super().save(*args, **kwargs)


class Guardianship(models.Model):
    """Links a parent account to a student. Created by the school, never self-claimed."""

    parent = models.ForeignKey(User, on_delete=models.CASCADE, related_name="children_links")
    student = models.ForeignKey(User, on_delete=models.CASCADE, related_name="guardian_links")
    relationship = models.CharField(max_length=30, blank=True)  # e.g. Mother, Uncle
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["parent", "student"], name="unique_parent_student"),
        ]

    def __str__(self):
        return f"{self.parent} -> {self.student}"

    def clean(self):
        if self.parent.role != User.Role.PARENT:
            raise ValidationError({"parent": "Must be a parent account."})
        if self.student.role != User.Role.STUDENT:
            raise ValidationError({"student": "Must be a student account."})
        if self.parent.school_id != self.student.school_id:
            raise ValidationError("Parent and student must belong to the same school.")


class ActivationCode(models.Model):
    """A one-time code someone uses to choose their own password: issued when an account is
    imported (printed on a login slip) or reissued by an admin. Only a keyed hash is stored;
    see apps/accounts/activation.py.
    """

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="activation_code")
    code_hash = models.CharField(max_length=64)
    expires_at = models.DateTimeField()
    created_by = models.ForeignKey(User, null=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"activation code for {self.user}"
