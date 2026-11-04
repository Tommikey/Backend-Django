from django.utils import timezone
from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated

from apps.accounts.permissions import IsOwnerOrAdmin, IsTeacherOrAdmin

from .models import StudySession
from .serializers import StudySessionSerializer


class StudySessionViewSet(viewsets.ModelViewSet):
    serializer_class = StudySessionSerializer
    queryset = StudySession.objects.select_related("classroom", "subject", "hosted_by").order_by(
        "starts_at"
    )
    owner_field = "hosted_by"

    def get_permissions(self):
        if self.action in {"update", "partial_update", "destroy"}:
            return [IsTeacherOrAdmin(), IsOwnerOrAdmin()]
        if self.action == "create":
            return [IsTeacherOrAdmin()]
        return [IsAuthenticated()]

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user
        if user.role == "student":
            qs = qs.filter(classroom__enrollments__student=user).distinct()
        if self.request.query_params.get("upcoming") in {"1", "true", "True"}:
            qs = qs.filter(starts_at__gte=timezone.now())
        return qs

    def perform_create(self, serializer):
        serializer.save(hosted_by=self.request.user)
