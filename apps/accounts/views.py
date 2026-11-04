from rest_framework import generics, viewsets
from rest_framework.exceptions import ValidationError
from rest_framework.throttling import ScopedRateThrottle
from rest_framework_simplejwt.views import TokenObtainPairView

from .access import InUse, RolePermissionsMixin, SchoolScopedMixin
from .models import Guardianship, User
from .permissions import IsAdmin, IsTeacherOrAdmin
from .serializers import GuardianshipSerializer, SchoolUserSerializer, UserSerializer
from .throttles import LoginUsernameThrottle


class LoginView(TokenObtainPairView):
    """POST {username, password} -> {access, refresh}. Rate-limited per username and per IP."""

    throttle_classes = [ScopedRateThrottle, LoginUsernameThrottle]
    throttle_scope = "login"


class MeView(generics.RetrieveUpdateAPIView):
    serializer_class = UserSerializer

    def get_object(self):
        return self.request.user


class UserViewSet(RolePermissionsMixin, SchoolScopedMixin, viewsets.ModelViewSet):
    """The school's people. Admins manage them; teachers can look them up."""

    serializer_class = SchoolUserSerializer
    queryset = User.objects.order_by("role", "last_name", "first_name", "username")
    write_permissions = (IsAdmin,)
    action_permissions = {"list": (IsTeacherOrAdmin,), "retrieve": (IsTeacherOrAdmin,)}

    def get_queryset(self):
        qs = super().get_queryset()
        if role := self.request.query_params.get("role"):
            qs = qs.filter(role=role)
        return qs

    def perform_destroy(self, instance):
        if instance == self.request.user:
            raise ValidationError("You can't delete your own account.")
        if has_history(instance):
            # deleting would cascade into marks, report cards, attendance and work
            raise InUse(
                "This person has school records (classes, marks, attendance or work). "
                "Deactivate the account instead (is_active: false)."
            )
        instance.delete()


# relations whose rows would be deleted with the user; any of them means "keep the account"
HISTORY = (
    "enrollments",
    "teaching_assignments",
    "scores",
    "term_results",
    "attendance_records",
    "submissions",
    "completions",
    "children_links",
    "guardian_links",
)


def has_history(user):
    return any(getattr(user, name).exists() for name in HISTORY)


class GuardianshipViewSet(RolePermissionsMixin, SchoolScopedMixin, viewsets.ModelViewSet):
    """Parent-to-student links. Admins manage them; parents and students see their own."""

    serializer_class = GuardianshipSerializer
    queryset = Guardianship.objects.select_related("parent", "student").order_by("-created_at")
    school_path = "student__school"
    write_permissions = (IsAdmin,)

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user
        if user.role == User.Role.PARENT:
            qs = qs.filter(parent=user)
        elif user.role == User.Role.STUDENT:
            qs = qs.filter(student=user)
        return qs
