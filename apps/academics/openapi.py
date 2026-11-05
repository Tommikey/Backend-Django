"""Response shapes for the API docs (OpenAPI) of hand-built responses.

These serializers only describe JSON; the views build it themselves. Shared references used
across apps live here.
"""

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import (
    OpenApiParameter,
    OpenApiResponse,
    extend_schema,
    extend_schema_view,
)
from rest_framework import serializers

CHILD_PARAM = OpenApiParameter(
    "child", int, description="Parents: only this child's (one of your linked children)"
)
# decorator for list endpoints parents can narrow with ?child=
child_filter = extend_schema_view(list=extend_schema(parameters=[CHILD_PARAM]))


class RefSerializer(serializers.Serializer):
    """A named object, e.g. a classroom or student."""

    id = serializers.IntegerField()
    name = serializers.CharField()


class StudentRefSerializer(RefSerializer):
    admission_number = serializers.CharField(help_text="Blank if the school doesn't use them")


class TermRefSerializer(RefSerializer):
    session = serializers.CharField(help_text="The session's name, e.g. 2025/2026")


class StatsCountsSerializer(serializers.Serializer):
    students = serializers.IntegerField()
    teachers = serializers.IntegerField()
    parents = serializers.IntegerField()
    classrooms = serializers.IntegerField()
    lessons = serializers.IntegerField()
    assessments = serializers.IntegerField()
    submissions = serializers.IntegerField()
    live_classes = serializers.IntegerField()


class StatsClassroomSerializer(RefSerializer):
    students = serializers.IntegerField(help_text="Enrolled in the current session")
    lessons = serializers.IntegerField()
    assessments = serializers.IntegerField()
    live_classes = serializers.IntegerField()
    avg_score_pct = serializers.FloatField(allow_null=True)


class StatsSerializer(serializers.Serializer):
    counts = StatsCountsSerializer()
    classrooms = StatsClassroomSerializer(many=True)


class ProgressLessonsSerializer(serializers.Serializer):
    total = serializers.IntegerField()
    completed = serializers.IntegerField()


class ProgressQuizzesSerializer(serializers.Serializer):
    total = serializers.IntegerField()
    submitted = serializers.IntegerField()
    avg_score_pct = serializers.FloatField(allow_null=True)


class ProgressClassroomSerializer(serializers.Serializer):
    classroom = RefSerializer()
    students = serializers.IntegerField()
    lessons = ProgressLessonsSerializer()
    quizzes = ProgressQuizzesSerializer()


class ProgressSerializer(serializers.Serializer):
    session = RefSerializer(allow_null=True)
    classrooms = ProgressClassroomSerializer(many=True)


class ProgressQuerySerializer(serializers.Serializer):
    session = serializers.IntegerField(required=False, help_text="Default: the current session")
    classroom = serializers.IntegerField(required=False)


class RolloverSummarySerializer(serializers.Serializer):
    promoted = serializers.IntegerField()
    repeating = serializers.IntegerField()
    moved = serializers.IntegerField()
    graduating = serializers.IntegerField()
    leaving = serializers.IntegerField()
    already_done = serializers.IntegerField(
        help_text="Placed, graduated or left in an earlier run; skipped"
    )
    teaching_assignments_copied = serializers.IntegerField()


class RolloverStudentSerializer(serializers.Serializer):
    student = StudentRefSerializer()
    from_classroom = RefSerializer()
    action = serializers.ChoiceField(choices=["promote", "repeat", "move", "graduate", "leave"])
    to_classroom = RefSerializer(allow_null=True, help_text="Null for graduate and leave")
    latest_average = serializers.CharField(
        allow_null=True, help_text="Average on the latest published report card this session"
    )
    note = serializers.CharField()
    error = serializers.CharField(help_text="Non-empty: this student can't be placed yet")


class RolloverResultSerializer(serializers.Serializer):
    from_session = RefSerializer()
    to_session = RefSerializer()
    committed = serializers.BooleanField()
    valid = serializers.BooleanField()
    summary = RolloverSummarySerializer()
    unpublished_terms = TermRefSerializer(many=True)
    students = RolloverStudentSerializer(many=True)


DOWNLOAD = extend_schema(
    responses={
        (200, "application/octet-stream"): OpenApiResponse(
            OpenApiTypes.BINARY, description="The file (local storage)"
        ),
        302: OpenApiResponse(description="Redirect to a link that expires in 5 minutes (S3)"),
        404: OpenApiResponse(description="No file, or not yours to see"),
    }
)
