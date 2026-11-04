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


class IsOwnerOrAdmin(BasePermission):
    """Object-level: admins may act on anything; others only on objects they own.

    The owning user field is read from the view's ``owner_field`` (default ``created_by``).
    """

    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated)

    def has_object_permission(self, request, view, obj):
        if request.user.role == "admin":
            return True
        owner_field = getattr(view, "owner_field", "created_by")
        return getattr(obj, f"{owner_field}_id") == request.user.pk
