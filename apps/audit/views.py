from datetime import datetime, time

from django.db.models import Q
from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import viewsets
from rest_framework.exceptions import ValidationError

from apps.academics.views import id_param
from apps.accounts.access import SchoolScopedMixin
from apps.accounts.permissions import IsAdmin

from .models import AuditEntry
from .serializers import AuditEntrySerializer

FILTERS = [
    OpenApiParameter("action", str, description='Exact ("scores.updated") or a family ("scores").'),
    OpenApiParameter("actor", int, description="Who did it (user id)."),
    OpenApiParameter("student", int, description="Everything about one student."),
    OpenApiParameter("target_type", str, description='e.g. "user", "term", "enrollment".'),
    OpenApiParameter("target_id", int),
    OpenApiParameter("classroom", int),
    OpenApiParameter("term", int),
    OpenApiParameter("since", str, description="A date (YYYY-MM-DD), inclusive."),
    OpenApiParameter("until", str, description="A date (YYYY-MM-DD), inclusive."),
]


def date_param(params, name, end_of_day=False):
    value = params.get(name)
    if not value:
        return None
    try:
        day = datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise ValidationError({name: "Use a date like 2026-11-05."}) from exc
    return timezone.make_aware(datetime.combine(day, time.max if end_of_day else time.min))


class AuditViewSet(SchoolScopedMixin, viewsets.ReadOnlyModelViewSet):
    """The school's audit log, newest first (admins). Who changed marks, attendance, comments,
    people, classes and settings, and who published or unpublished results."""

    queryset = AuditEntry.objects.all()
    serializer_class = AuditEntrySerializer
    permission_classes = [IsAdmin]

    @extend_schema(parameters=FILTERS)
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    def get_queryset(self):
        qs = super().get_queryset()
        params = self.request.query_params
        if action := params.get("action"):
            qs = (
                qs.filter(action=action)
                if "." in action
                else qs.filter(action__startswith=f"{action}.")
            )
        if (actor := id_param(params, "actor")) is not None:
            qs = qs.filter(actor_id=actor)
        if (student := id_param(params, "student")) is not None:
            qs = qs.filter(
                Q(target_type="user", target_id=student)
                | Q(changes__contains=[{"student": student}])
                | Q(context__student__id=student)
            )
        if target_type := params.get("target_type"):
            qs = qs.filter(target_type=target_type)
        if (target_id := id_param(params, "target_id")) is not None:
            qs = qs.filter(target_id=target_id)
        for name in ("classroom", "term"):
            if (value := id_param(params, name)) is not None:
                qs = qs.filter(**{f"context__{name}__id": value})
        if since := date_param(params, "since"):
            qs = qs.filter(created_at__gte=since)
        if until := date_param(params, "until", end_of_day=True):
            qs = qs.filter(created_at__lte=until)
        return qs
