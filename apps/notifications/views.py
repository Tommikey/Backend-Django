from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Notification
from .serializers import CountSerializer, NotificationSerializer, NotificationSettingsSerializer


class NotificationViewSet(viewsets.ReadOnlyModelViewSet):
    """Your notifications, newest first. ``?unread=true`` for the unread ones only."""

    queryset = Notification.objects.all()  # narrowed to your own in get_queryset
    serializer_class = NotificationSerializer

    def get_queryset(self):
        qs = super().get_queryset().filter(recipient=self.request.user)
        if self.request.query_params.get("unread") in ("true", "1"):
            qs = qs.filter(read_at__isnull=True)
        if kind := self.request.query_params.get("kind"):
            qs = qs.filter(kind=kind)
        return qs

    @extend_schema(
        parameters=[
            OpenApiParameter("unread", bool),
            OpenApiParameter("kind", enum=Notification.Kind.values),
        ]
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @extend_schema(request=None, responses=NotificationSerializer)
    @action(detail=True, methods=["post"])
    def read(self, request, pk=None):
        note = self.get_object()
        if note.read_at is None:
            note.read_at = timezone.now()
            note.save(update_fields=["read_at"])
        return Response(self.get_serializer(note).data)

    @extend_schema(request=None, responses=CountSerializer)
    @action(detail=False, methods=["post"], url_path="read-all")
    def read_all(self, request):
        Notification.objects.filter(recipient=request.user, read_at__isnull=True).update(
            read_at=timezone.now()
        )
        return Response({"unread": 0})

    @extend_schema(responses=CountSerializer)
    @action(detail=False, url_path="unread-count")
    def unread_count(self, request):
        count = Notification.objects.filter(recipient=request.user, read_at__isnull=True).count()
        return Response({"unread": count})


class NotificationSettingsView(APIView):
    """GET / PATCH {email}: whether your notifications are also emailed to you."""

    @extend_schema(responses=NotificationSettingsSerializer)
    def get(self, request):
        return Response(NotificationSettingsSerializer(request.user).data)

    @extend_schema(request=NotificationSettingsSerializer, responses=NotificationSettingsSerializer)
    def patch(self, request):
        serializer = NotificationSettingsSerializer(request.user, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        request.user.email_notifications = serializer.validated_data.get(
            "email_notifications", request.user.email_notifications
        )
        request.user.save(update_fields=["email_notifications"])
        return Response(NotificationSettingsSerializer(request.user).data)
