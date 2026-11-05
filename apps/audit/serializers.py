from rest_framework import serializers

from .models import AuditEntry


class AuditEntrySerializer(serializers.ModelSerializer):
    changes = serializers.JSONField(
        read_only=True,
        help_text="{field: [old, new]} for one record; for a score sheet or register, a list "
        "of {student, student_name, ..., old, new} rows.",
    )
    context = serializers.JSONField(
        read_only=True, help_text="Where it happened: classroom, subject, term, date..."
    )

    class Meta:
        model = AuditEntry
        fields = [
            "id",
            "created_at",
            "action",
            "actor",
            "actor_name",
            "target_type",
            "target_id",
            "target_label",
            "changes",
            "context",
            "ip",
        ]
        read_only_fields = fields
