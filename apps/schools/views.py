from django.db import transaction
from django.db.models import ProtectedError
from django.http import Http404
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view
from rest_framework import generics, status, viewsets
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from apps.academics.models import AcademicSession
from apps.academics.rules import current_session
from apps.accounts.access import InUse, RolePermissionsMixin, SafeDestroyMixin, SchoolScopedMixin
from apps.accounts.permissions import IsAdmin
from apps.accounts.serializers import UserSerializer
from apps.audit import log as audit
from apps.audit.log import AuditedMixin
from apps.results.models import Score

from . import openapi
from .models import AssessmentComponent, GradeBand, Level
from .serializers import (
    AssessmentComponentSerializer,
    ComponentSetSerializer,
    GradeBandSerializer,
    GradeBandSetSerializer,
    LevelSerializer,
    OnboardSerializer,
    SchoolSerializer,
)
from .services import onboard_school


class OnboardView(APIView):
    """Public sign-up for a new school: creates the school, its preset setup and first admin."""

    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "onboard"

    @extend_schema(request=OnboardSerializer, responses={201: openapi.OnboardResultSerializer})
    def post(self, request):
        serializer = OnboardSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        school, admin = onboard_school(
            name=data["school_name"], system=data["system"], admin=data["admin"]
        )
        return Response(
            {"school": SchoolSerializer(school).data, "admin": UserSerializer(admin).data},
            status=status.HTTP_201_CREATED,
        )


class MySchoolView(AuditedMixin, generics.RetrieveUpdateAPIView):
    """The user's own school and its settings. Members read; admins edit."""

    serializer_class = SchoolSerializer
    audit_fields = ("name", "show_position", "use_gpa", "term_labels", "timezone")

    def get_permissions(self):
        if self.request.method in {"PUT", "PATCH"}:
            return [IsAdmin()]
        return [IsAuthenticated()]

    def get_object(self):
        school = self.request.user.school
        if school is None:
            raise Http404("You don't belong to a school.")
        return school


class LevelViewSet(
    RolePermissionsMixin, SchoolScopedMixin, SafeDestroyMixin, viewsets.ModelViewSet
):
    serializer_class = LevelSerializer
    queryset = Level.objects.order_by("order")
    write_permissions = (IsAdmin,)


class ReplaceAllConfigView(APIView):
    """GET the school's list; PUT a whole new list (admin only), validated as a set.

    Editing the set as a whole is what lets us enforce rules like "adds up to 100".
    """

    model = None
    item_serializer = None
    set_serializer = None
    key = ""  # request/response field holding the list

    def get_permissions(self):
        if self.request.method == "PUT":
            return [IsAdmin()]
        return [IsAuthenticated()]

    def get_items(self):
        return self.model.objects.filter(school_id=self.request.user.school_id)

    def get(self, request):
        items = self.item_serializer(self.get_items(), many=True).data
        return Response({**self.extra_response(), self.key: items})

    @transaction.atomic
    def put(self, request):
        serializer = self.set_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.check_replaceable(request)
        before = self.item_serializer(self.get_items(), many=True).data
        try:
            self.get_items().delete()
        except ProtectedError as exc:  # something came to depend on it meanwhile
            raise InUse() from exc
        self.model.objects.bulk_create(
            self.model(school=request.user.school, **self.extra_fields(i), **item)
            for i, item in enumerate(serializer.validated_data[self.key], 1)
        )
        response = self.get(request)
        after = response.data[self.key]
        strip = lambda items: [{k: v for k, v in i.items() if k != "id"} for i in items]  # noqa: E731
        if strip(before) != strip(after):
            audit.record(
                f"{self.key}.replaced",
                school=request.user.school,
                request=request,
                label=self.audit_label(),
                changes={"old": strip(before), "new": strip(after)},
            )
        return response

    def audit_label(self):
        return self.key.replace("_", " ").capitalize()

    def extra_fields(self, position):
        return {}

    def extra_response(self):
        return {}

    def check_replaceable(self, request):
        """Hook: refuse the replacement (raise) when existing data depends on the old set."""


SESSION_PARAM = OpenApiParameter(
    "session",
    int,
    description="Whose split: a session's id. Default: the current session (the school's "
    "default split if it has no session yet).",
)


@extend_schema_view(
    get=extend_schema(parameters=[SESSION_PARAM], responses=openapi.ScoreSplitSerializer),
    put=extend_schema(
        parameters=[SESSION_PARAM],
        request=ComponentSetSerializer,
        responses=openapi.ScoreSplitSerializer,
    ),
)
class ComponentsView(ReplaceAllConfigView):
    """How a subject's term score is split in a session, e.g. CA1 20 + CA2 20 + Exam 60.

    Each session has its own split, copied from the previous session when it is created, so
    next year's can be changed (?session=<next>) without touching this year's marks. A split
    is locked once scores have been entered against it.
    """

    model = AssessmentComponent
    item_serializer = AssessmentComponentSerializer
    set_serializer = ComponentSetSerializer
    key = "components"

    def audit_label(self):
        session = self.split_session()
        return f"Score split, {session.name}" if session else "Score split (school default)"

    def split_session(self):
        if not hasattr(self, "_split_session"):
            school_id = self.request.user.school_id
            raw = self.request.query_params.get("session")
            if raw:
                if not raw.isdigit():
                    raise ValidationError({"session": "Must be an ID (a whole number)."})
                session = AcademicSession.objects.filter(school_id=school_id, pk=raw).first()
                if session is None:
                    raise Http404("No such session.")
            else:
                session = current_session(school_id)
            self._split_session = session
        return self._split_session

    def get_items(self):
        return self.request.user.school.score_split(self.split_session())

    def extra_fields(self, position):
        # in the order they were sent, in the chosen session's split
        return {"order": position, "session": self.split_session()}

    def extra_response(self):
        session = self.split_session()
        return {"session": {"id": session.pk, "name": session.name} if session else None}

    def check_replaceable(self, request):
        if Score.objects.filter(component__in=self.get_items()).exists():
            session = self.split_session()
            raise InUse(
                f"Scores have already been entered with {session or 'this'} split, so it "
                "can't be replaced. Clear those scores, or change the next session's split."
            )


@extend_schema_view(
    get=extend_schema(responses=GradeBandSetSerializer),
    put=extend_schema(request=GradeBandSetSerializer, responses=GradeBandSetSerializer),
)
class GradeBandsView(ReplaceAllConfigView):
    """The grade scale, e.g. A1 from 75, B2 from 70..."""

    model = GradeBand
    item_serializer = GradeBandSerializer
    set_serializer = GradeBandSetSerializer
    key = "grade_bands"
