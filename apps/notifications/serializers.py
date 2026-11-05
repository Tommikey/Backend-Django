from rest_framework import serializers

from .models import Notification


class NotificationSerializer(serializers.ModelSerializer):
    is_read = serializers.SerializerMethodField()
    data = serializers.JSONField(
        read_only=True,
        help_text="Ids to open the subject: term + student (results_published), student + "
        "date + classroom (absent), assessment (work_set), live_class (live_class_soon).",
    )

    class Meta:
        model = Notification
        fields = ["id", "kind", "title", "body", "data", "is_read", "read_at", "created_at"]
        read_only_fields = fields

    def get_is_read(self, note) -> bool:
        return note.read_at is not None


class NotificationSettingsSerializer(serializers.Serializer):
    email = serializers.BooleanField(
        source="email_notifications",
        help_text="Also send notifications by email (needs an email address on the account).",
    )
    has_email = serializers.SerializerMethodField()

    def get_has_email(self, user) -> bool:
        return bool(user.email)


class CountSerializer(serializers.Serializer):
    unread = serializers.IntegerField()
