"""Shared access rules for the API viewsets.

Default policy for every viewset that uses these mixins:
- any logged-in user can read (list / retrieve)
- teachers and admins can create
- teachers and admins can update / delete; with ``owner_scoped`` only the owner or an admin
- students only see rows reachable through their own enrollments (``student_scope``)
"""

from rest_framework.permissions import IsAuthenticated

from .permissions import IsOwnerOrAdmin, IsTeacherOrAdmin

WRITE_ACTIONS = frozenset({"update", "partial_update", "destroy"})


class RolePermissionsMixin:
    # extra actions with their own rules, e.g. {"complete": (IsStudent,)}
    action_permissions: dict = {}
    # restrict update/delete to the object's owner (see IsOwnerOrAdmin / owner_field)
    owner_scoped = False

    def get_permissions(self):
        if self.action in self.action_permissions:
            classes = self.action_permissions[self.action]
        elif self.action == "create":
            classes = (IsTeacherOrAdmin,)
        elif self.action in WRITE_ACTIONS and self.owner_scoped:
            classes = (IsTeacherOrAdmin, IsOwnerOrAdmin)
        elif self.action in WRITE_ACTIONS:
            classes = (IsTeacherOrAdmin,)
        else:
            classes = (IsAuthenticated,)
        return [cls() for cls in classes]


class OwnedObjectMixin:
    # user field stamped on create; also read by IsOwnerOrAdmin
    owner_field = "created_by"

    def perform_create(self, serializer):
        serializer.save(**{self.owner_field: self.request.user})


class StudentScopedQuerysetMixin:
    # ORM lookup from this model to the student, e.g. "classroom__enrollments__student"
    student_scope: str = ""

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user
        if user.role == "student" and self.student_scope:
            qs = qs.filter(**{self.student_scope: user})
            if "__" in self.student_scope:
                # lookups through a related table can match the same row more than once
                qs = qs.distinct()
        return qs
