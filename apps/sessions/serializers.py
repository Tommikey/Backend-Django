from rest_framework import serializers

from apps.accounts.access import SameSchoolSerializerMixin

from .models import StudySession


class StudySessionSerializer(SameSchoolSerializerMixin, serializers.ModelSerializer):
    classroom_name = serializers.CharField(source="classroom.name", read_only=True)
    subject_name = serializers.CharField(source="subject.name", read_only=True)
    hosted_by_name = serializers.CharField(source="hosted_by.get_full_name", read_only=True)

    class Meta:
        model = StudySession
        fields = [
            "id",
            "title",
            "description",
            "classroom",
            "classroom_name",
            "subject",
            "subject_name",
            "hosted_by",
            "hosted_by_name",
            "starts_at",
            "ends_at",
            "join_url",
            "created_at",
        ]
        read_only_fields = ["hosted_by", "created_at"]
