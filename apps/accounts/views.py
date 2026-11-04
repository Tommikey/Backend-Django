from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from drf_spectacular.utils import extend_schema
from rest_framework import generics, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenBlacklistView, TokenObtainPairView

from . import openapi
from .access import InUse, RolePermissionsMixin, SchoolScopedMixin
from .activation import check_code, issue_codes
from .authentication import can_sign_in, end_sessions
from .models import Guardianship, User
from .permissions import IsAdmin, IsTeacherOrAdmin
from .serializers import (
    ActivateSerializer,
    ActivationCodeIssuedSerializer,
    GuardianshipSerializer,
    MeSerializer,
    PasswordChangeSerializer,
    SchoolUserSerializer,
)
from .throttles import LoginUsernameThrottle


class LoginView(TokenObtainPairView):
    """POST {username, password} -> {access, refresh}. Rate-limited per username and per IP."""

    throttle_classes = [ScopedRateThrottle, LoginUsernameThrottle]
    throttle_scope = "login"


class ActivateView(APIView):
    """POST {username, code, new_password}: first sign-in with an activation code (from an
    import or an admin). Sets the password, uses up the code, and signs you in. Rate-limited
    like login; a wrong username or code gets the same answer."""

    authentication_classes = []
    permission_classes = []
    throttle_classes = [ScopedRateThrottle, LoginUsernameThrottle]
    throttle_scope = "login"

    @extend_schema(request=ActivateSerializer, responses=openapi.TokenPairSerializer)
    @transaction.atomic
    def post(self, request):
        serializer = ActivateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        user = User.objects.filter(username__iexact=data["username"].strip()).first()
        if user is None or not can_sign_in(user) or not check_code(user, data["code"]):
            raise ValidationError({"code": "That username and activation code don't match."})
        try:
            validate_password(data["new_password"], user)
        except DjangoValidationError as exc:
            raise ValidationError({"new_password": exc.messages}) from exc
        user.set_password(data["new_password"])
        user.save(update_fields=["password"])
        user.activation_code.delete()
        end_sessions(user)  # a reissued code doubles as a reset: other sessions end
        refresh = RefreshToken.for_user(user)
        return Response({"access": str(refresh.access_token), "refresh": str(refresh)})


class LogoutView(TokenBlacklistView):
    """POST {refresh}: retire this device's refresh token. Its access token runs out on its own
    (at most an hour); the client should drop both."""


class PasswordChangeView(APIView):
    """POST {current_password, new_password}: change your own password. Every other session
    ends; the response carries fresh tokens so this device stays signed in."""

    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "password"

    @extend_schema(request=PasswordChangeSerializer, responses=openapi.TokenPairSerializer)
    def post(self, request):
        serializer = PasswordChangeSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        user = request.user
        user.set_password(serializer.validated_data["new_password"])
        user.save(update_fields=["password"])
        end_sessions(user)
        refresh = RefreshToken.for_user(user)
        return Response({"access": str(refresh.access_token), "refresh": str(refresh)})


class MeView(generics.RetrieveUpdateAPIView):
    """GET: your profile and what a client needs to start (see MeSerializer). PATCH: edit your
    name and email."""

    serializer_class = MeSerializer

    def get_object(self):
        return self.request.user


class UserViewSet(RolePermissionsMixin, SchoolScopedMixin, viewsets.ModelViewSet):
    """The school's people. Admins manage them; teachers can look them up."""

    serializer_class = SchoolUserSerializer
    search_fields = ["username", "first_name", "last_name", "email"]
    ordering_fields = ["last_name", "first_name", "username", "role", "date_joined"]
    queryset = User.objects.select_related("activation_code").order_by(
        "role", "last_name", "first_name", "username"
    )
    write_permissions = (IsAdmin,)
    action_permissions = {
        "list": (IsTeacherOrAdmin,),
        "retrieve": (IsTeacherOrAdmin,),
        "activation_code": (IsAdmin,),
    }

    def get_queryset(self):
        qs = super().get_queryset()
        if role := self.request.query_params.get("role"):
            qs = qs.filter(role=role)
        return qs

    @extend_schema(request=None, responses={201: ActivationCodeIssuedSerializer})
    @action(detail=True, methods=["post"], url_path="activation-code")
    def activation_code(self, request, pk=None):
        """Issue a fresh one-time code (replacing any earlier one) for the person to choose a
        new password with. Their current password keeps working until they use it."""
        user = self.get_object()
        code, expires_at = issue_codes([user], request.user)[user.pk]
        return Response(
            {"user": user.pk, "username": user.username, "code": code, "expires_at": expires_at},
            status=201,
        )

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
    search_fields = [
        "parent__first_name",
        "parent__last_name",
        "parent__username",
        "student__first_name",
        "student__last_name",
        "student__username",
    ]
    ordering_fields = ["created_at", "student__last_name", "parent__last_name"]
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
