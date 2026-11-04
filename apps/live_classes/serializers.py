from rest_framework import serializers

from apps.academics.serializers import TeachingScopeSerializerMixin, term_field
from apps.accounts.access import SameSchoolSerializerMixin

from .models import LiveClass


class LiveClassSerializer(
    TeachingScopeSerializerMixin, SameSchoolSerializerMixin, serializers.ModelSerializer
):
    term = term_field()
    term_name = serializers.CharField(source="term.name", read_only=True)
    classroom_name = serializers.CharField(source="classroom.name", read_only=True)
    subject_name = serializers.CharField(source="subject.name", read_only=True)
    hosted_by_name = serializers.CharField(
        source="hosted_by.display_name", read_only=True, default=None
    )

    class Meta:
        model = LiveClass
        fields = [
            "id",
            "title",
            "description",
            "classroom",
            "classroom_name",
            "subject",
            "subject_name",
            "term",
            "term_name",
            "hosted_by",
            "hosted_by_name",
            "starts_at",
            "ends_at",
            "join_url",
            "created_at",
        ]
        read_only_fields = ["hosted_by", "created_at"]

    def validate(self, attrs):
        attrs = super().validate(attrs)
        live = self.instance
        starts = attrs.get("starts_at", live.starts_at if live else None)
        ends = attrs.get("ends_at", live.ends_at if live else None)
        if starts and ends and ends <= starts:
            raise serializers.ValidationError({"ends_at": "Must be after starts_at."})
        return attrs
