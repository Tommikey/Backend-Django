from django.utils import timezone
from rest_framework import viewsets

from apps.accounts.access import (
    OwnedObjectMixin,
    RolePermissionsMixin,
    StudentScopedQuerysetMixin,
)

from .models import StudySession
from .serializers import StudySessionSerializer


class StudySessionViewSet(
    RolePermissionsMixin, OwnedObjectMixin, StudentScopedQuerysetMixin, viewsets.ModelViewSet
):
    serializer_class = StudySessionSerializer
    queryset = StudySession.objects.select_related("classroom", "subject", "hosted_by").order_by(
        "starts_at"
    )
    owner_field = "hosted_by"
    owner_scoped = True
    student_scope = "classroom__enrollments__student"

    def get_queryset(self):
        qs = super().get_queryset()
        if self.request.query_params.get("upcoming") in {"1", "true", "True"}:
            qs = qs.filter(starts_at__gte=timezone.now())
        return qs
