from rest_framework.permissions import BasePermission

from .rules import teaches


class TeachesSubjectOrAdmin(BasePermission):
    """Object-level: admins, or the teacher assigned to the object's class + subject for the
    session of its term. ``teaching_path`` on the view leads from the object to the thing that
    has classroom/subject/term (e.g. ``assessment`` for a submission); empty means the object.
    """

    message = "You don't teach this subject to this class."

    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated)

    def has_object_permission(self, request, view, obj):
        if request.user.role == "admin":
            return True
        target = obj
        for hop in filter(None, getattr(view, "teaching_path", "").split(".")):
            target = getattr(target, hop)
        return teaches(request.user, target.classroom_id, target.subject_id, target.term.session_id)
