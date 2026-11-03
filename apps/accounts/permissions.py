from rest_framework.permissions import BasePermission


class RolePermission(BasePermission):
    allowed_roles: frozenset = frozenset()

    def has_permission(self, request, view):
        user = request.user
        return bool(user and user.is_authenticated and user.role in self.allowed_roles)


class IsAdmin(RolePermission):
    allowed_roles = frozenset({"admin"})


class IsTeacher(RolePermission):
    allowed_roles = frozenset({"teacher"})


class IsStudent(RolePermission):
    allowed_roles = frozenset({"student"})


class IsTeacherOrAdmin(RolePermission):
    allowed_roles = frozenset({"teacher", "admin"})
