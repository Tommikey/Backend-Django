from rest_framework import serializers

from .models import Job


class JobSerializer(serializers.ModelSerializer):
    url = serializers.HyperlinkedIdentityField(view_name="jobs:job-detail")
    result = serializers.JSONField(
        read_only=True, help_text="What the job produced, once done; its shape depends on kind."
    )

    class Meta:
        model = Job
        fields = [
            "id",
            "url",
            "kind",
            "status",
            "params",
            "result",
            "error",
            "created_by",
            "created_at",
            "started_at",
            "finished_at",
        ]
        read_only_fields = fields
