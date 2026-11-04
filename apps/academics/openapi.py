"""Response shapes for the API docs (OpenAPI) of hand-built responses.

These serializers only describe JSON; the views build it themselves. Shared references used
across apps live here.
"""

from rest_framework import serializers


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
