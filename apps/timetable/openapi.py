"""Response shapes of the timetable views, for the API docs."""

from rest_framework import serializers

from apps.academics.openapi import RefSerializer


class PeriodOutSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    starts_at = serializers.CharField(help_text="HH:MM")
    ends_at = serializers.CharField(help_text="HH:MM")
    is_break = serializers.BooleanField()


class TimetableLessonSerializer(serializers.Serializer):
    slot = serializers.IntegerField()
    subject = RefSerializer()
    teacher = RefSerializer(required=False, help_text="On class timetables.")
    classroom = RefSerializer(required=False, help_text="On teacher timetables.")


class DaySerializer(serializers.Serializer):
    day = serializers.IntegerField(help_text="1 = Monday ... 6 = Saturday")
    name = serializers.CharField()
    lessons = TimetableLessonSerializer(
        many=True, allow_null=True, help_text="One per period, in period order; null if free."
    )


class ClassWeekSerializer(serializers.Serializer):
    classroom = RefSerializer()
    session = RefSerializer()
    can_edit = serializers.BooleanField()
    periods = PeriodOutSerializer(many=True)
    days = DaySerializer(many=True)


class TeacherWeekSerializer(serializers.Serializer):
    teacher = RefSerializer()
    session = RefSerializer()
    periods = PeriodOutSerializer(many=True)
    days = DaySerializer(many=True)


class TodayLessonSerializer(PeriodOutSerializer):
    slot = serializers.IntegerField()
    subject = RefSerializer()
    teacher = RefSerializer()
    classroom = RefSerializer()
