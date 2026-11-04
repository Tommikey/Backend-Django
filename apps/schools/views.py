from django.db import transaction
from django.http import Http404
from rest_framework import generics, status, viewsets
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.access import RolePermissionsMixin, SchoolScopedMixin
from apps.accounts.permissions import IsAdmin
from apps.accounts.serializers import UserSerializer

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


class MySchoolView(generics.RetrieveUpdateAPIView):
    """The user's own school and its settings. Members read; admins edit."""

    serializer_class = SchoolSerializer

    def get_permissions(self):
        if self.request.method in {"PUT", "PATCH"}:
            return [IsAdmin()]
        return [IsAuthenticated()]

    def get_object(self):
        school = self.request.user.school
        if school is None:
            raise Http404("You don't belong to a school.")
        return school


class LevelViewSet(RolePermissionsMixin, SchoolScopedMixin, viewsets.ModelViewSet):
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
        return Response({self.key: self.item_serializer(self.get_items(), many=True).data})

    @transaction.atomic
    def put(self, request):
        serializer = self.set_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.get_items().delete()
        self.model.objects.bulk_create(
            self.model(school=request.user.school, **self.extra_fields(i), **item)
            for i, item in enumerate(serializer.validated_data[self.key], 1)
        )
        return self.get(request)

    def extra_fields(self, position):
        return {}


class ComponentsView(ReplaceAllConfigView):
    """How a subject's term score is split, e.g. CA1 20 + CA2 20 + Exam 60."""

    model = AssessmentComponent
    item_serializer = AssessmentComponentSerializer
    set_serializer = ComponentSetSerializer
    key = "components"

    def extra_fields(self, position):
        return {"order": position}  # the order they were sent in


class GradeBandsView(ReplaceAllConfigView):
    """The grade scale, e.g. A1 from 75, B2 from 70..."""

    model = GradeBand
    item_serializer = GradeBandSerializer
    set_serializer = GradeBandSetSerializer
    key = "grade_bands"
