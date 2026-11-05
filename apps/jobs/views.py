from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import viewsets

from apps.accounts.access import SchoolScopedMixin

from .models import Job
from .serializers import JobSerializer


class JobViewSet(SchoolScopedMixin, viewsets.ReadOnlyModelViewSet):
    """Background work and its progress. Poll a job's ``url`` until ``status`` is ``done``
    (see ``result``) or ``failed`` (see ``error``). Admins see the school's jobs; everyone
    else, the ones they started."""

    queryset = Job.objects.select_related("created_by")
    serializer_class = JobSerializer

    @extend_schema(
        parameters=[
            OpenApiParameter("kind", enum=Job.Kind.values),
            OpenApiParameter("status", enum=Job.Status.values),
        ]
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user
        if user.role != "admin":
            qs = qs.filter(created_by=user)
        for field in ("kind", "status"):
            if value := self.request.query_params.get(field):
                qs = qs.filter(**{field: value})
        return qs
