from django.utils import timezone
from rest_framework import viewsets

from apps.academics.permissions import TeachesSubjectOrAdmin
from apps.academics.rules import enrolled_exists
from apps.academics.views import filter_by_params
from apps.accounts.access import (
    AudienceScopedMixin,
    OwnedObjectMixin,
    RolePermissionsMixin,
    SchoolScopedMixin,
)

from .models import LiveClass
from .serializers import LiveClassSerializer


class LiveClassViewSet(
    RolePermissionsMixin,
    SchoolScopedMixin,
    AudienceScopedMixin,
    OwnedObjectMixin,
    viewsets.ModelViewSet,
):
    """Live classes. The subject's teacher (or an admin) schedules and edits them."""

    serializer_class = LiveClassSerializer
    queryset = LiveClass.objects.select_related(
        "classroom__level", "subject", "term", "hosted_by"
    ).order_by("starts_at")
    owner_field = "hosted_by"
    write_object_permissions = (TeachesSubjectOrAdmin,)
    school_path = "classroom__school"

    def scope_student(self, qs, user):
        return qs.filter(enrolled_exists(user))

    def get_queryset(self):
        qs = filter_by_params(
            super().get_queryset(), self.request.query_params, "classroom", "subject", "term"
        )
        if self.request.query_params.get("upcoming") in {"1", "true", "True"}:
            qs = qs.filter(starts_at__gte=timezone.now())
        return qs
