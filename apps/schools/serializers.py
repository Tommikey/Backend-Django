import zoneinfo
from decimal import Decimal

from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers

from apps.accounts.access import SameSchoolSerializerMixin
from apps.accounts.models import User

from .models import AssessmentComponent, GradeBand, Level, School


class SchoolSerializer(serializers.ModelSerializer):
    system_name = serializers.CharField(source="get_system_display", read_only=True)

    class Meta:
        model = School
        fields = [
            "id",
            "name",
            "slug",
            "system",
            "system_name",
            "show_position",
            "use_gpa",
            "term_labels",
            "timezone",
            "created_at",
        ]
        # the system only picks the starting preset; changing it later would mean nothing
        read_only_fields = ["slug", "system", "created_at"]

    def validate_timezone(self, value):
        if value not in zoneinfo.available_timezones():
            raise serializers.ValidationError('Give an IANA time zone, e.g. "Africa/Lagos".')
        return value

    def validate_term_labels(self, value):
        if (
            not isinstance(value, list)
            or not 1 <= len(value) <= 4
            or not all(isinstance(v, str) and v.strip() for v in value)
        ):
            raise serializers.ValidationError("Give 1 to 4 term names.")
        if len({v.strip().lower() for v in value}) != len(value):
            raise serializers.ValidationError("Term names must be different.")
        return [v.strip() for v in value]


class OnboardAdminSerializer(serializers.Serializer):
    username = serializers.CharField(max_length=150)
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, style={"input_type": "password"})
    first_name = serializers.CharField(max_length=150, required=False, default="")
    last_name = serializers.CharField(max_length=150, required=False, default="")

    def validate_username(self, value):
        if User.objects.filter(username__iexact=value).exists():
            raise serializers.ValidationError("This username is taken.")
        return value

    def validate_password(self, value):
        validate_password(value)
        return value


class OnboardSerializer(serializers.Serializer):
    school_name = serializers.CharField(max_length=200)
    system = serializers.ChoiceField(choices=School.System.choices)
    admin = OnboardAdminSerializer()


class LevelSerializer(SameSchoolSerializerMixin, serializers.ModelSerializer):
    class Meta:
        model = Level
        fields = ["id", "name", "order"]

    def validate_name(self, value):
        return self.unique_in_school("name", value)


class AssessmentComponentSerializer(serializers.ModelSerializer):
    class Meta:
        model = AssessmentComponent
        fields = ["id", "name", "max_score", "order"]
        read_only_fields = ["order"]


class GradeBandSerializer(serializers.ModelSerializer):
    class Meta:
        model = GradeBand
        fields = ["id", "label", "min_score", "remark", "grade_point"]


def _check_unique(items, key, message):
    seen = [str(item[key]).strip().lower() for item in items]
    if len(set(seen)) != len(seen):
        raise serializers.ValidationError(message)


class ComponentSetSerializer(serializers.Serializer):
    """The whole score split at once, so it can be checked to add up to 100."""

    components = AssessmentComponentSerializer(many=True)

    def validate_components(self, value):
        if not value:
            raise serializers.ValidationError("Give at least one component.")
        _check_unique(value, "name", "Component names must be different.")
        total = sum(c["max_score"] for c in value)
        if total != 100:
            raise serializers.ValidationError(f"Maximum scores must add up to 100 (got {total}).")
        return value


class GradeBandSetSerializer(serializers.Serializer):
    """The whole grade scale at once, so it can be checked for completeness."""

    grade_bands = GradeBandSerializer(many=True)

    def validate_grade_bands(self, value):
        if not value:
            raise serializers.ValidationError("Give at least one grade.")
        _check_unique(value, "label", "Grade labels must be different.")
        _check_unique(value, "min_score", "Each grade needs a different minimum score.")
        if any(not Decimal(0) <= b["min_score"] <= Decimal(100) for b in value):
            raise serializers.ValidationError("Minimum scores must be between 0 and 100.")
        if not any(b["min_score"] == 0 for b in value):
            raise serializers.ValidationError("The lowest grade must start at 0.")
        return value
