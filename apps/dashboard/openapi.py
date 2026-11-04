"""Response shape of the dashboard for the API docs (the view builds the JSON)."""

from rest_framework import serializers

from apps.academics.openapi import RefSerializer, TermRefSerializer
from apps.assessments.models import Assessment
from apps.attendance.openapi import AttendanceSummarySerializer


class LiveClassItemSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    title = serializers.CharField()
    classroom = RefSerializer()
    subject = RefSerializer()
    starts_at = serializers.DateTimeField()
    ends_at = serializers.DateTimeField(allow_null=True)
    join_url = serializers.URLField()


class LatestCardSerializer(serializers.Serializer):
    term = TermRefSerializer()
    published_at = serializers.DateTimeField()
    average = serializers.CharField(allow_null=True)
    position = serializers.IntegerField(allow_null=True)
    out_of = serializers.IntegerField(allow_null=True)
    gpa = serializers.CharField(allow_null=True)


class DueWorkSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    title = serializers.CharField()
    type = serializers.ChoiceField(choices=Assessment.Type.choices)
    subject = RefSerializer()
    due_at = serializers.DateTimeField(allow_null=True)


class StudentBlockSerializer(serializers.Serializer):
    due_work = DueWorkSerializer(many=True, help_text="The next 5 open items, soonest first")
    due_count = serializers.IntegerField(help_text="Unsubmitted and not overdue")
    overdue_count = serializers.IntegerField()
    upcoming_live_classes = LiveClassItemSerializer(many=True)
    attendance = AttendanceSummarySerializer(allow_null=True)
    latest_report_card = LatestCardSerializer(allow_null=True)


class ChildSerializer(serializers.Serializer):
    student = RefSerializer()
    classroom = RefSerializer(allow_null=True)
    due_count = serializers.IntegerField(help_text="Unsubmitted and not overdue")
    overdue_count = serializers.IntegerField()
    attendance = AttendanceSummarySerializer(allow_null=True)
    latest_report_card = LatestCardSerializer(allow_null=True)


class ParentBlockSerializer(serializers.Serializer):
    children = ChildSerializer(many=True)


class RegisterStatusSerializer(serializers.Serializer):
    classroom = RefSerializer()
    taken_today = serializers.BooleanField()


class ToGradeSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    title = serializers.CharField()
    classroom = RefSerializer()
    subject = RefSerializer()
    ungraded = serializers.IntegerField()


class TeacherBlockSerializer(serializers.Serializer):
    registers = RegisterStatusSerializer(many=True, help_text="Your form classes")
    to_grade_count = serializers.IntegerField()
    to_grade = ToGradeSerializer(many=True)
    upcoming_live_classes = LiveClassItemSerializer(many=True)


class PeopleSerializer(serializers.Serializer):
    students = serializers.IntegerField()
    teachers = serializers.IntegerField()
    parents = serializers.IntegerField()


class MissingRegisterSerializer(serializers.Serializer):
    classroom = RefSerializer()
    form_teacher = serializers.CharField(allow_null=True)


class TermStatusSerializer(serializers.Serializer):
    term = TermRefSerializer()
    published = serializers.BooleanField()
    classes = serializers.IntegerField()
    scores_entered = serializers.IntegerField()


class AdminBlockSerializer(serializers.Serializer):
    people = PeopleSerializer()
    registers_missing_today = MissingRegisterSerializer(many=True)
    term_status = TermStatusSerializer(allow_null=True)


class DashboardSerializer(serializers.Serializer):
    role = serializers.CharField()
    today = serializers.DateField()
    term = TermRefSerializer(allow_null=True)
    admin = AdminBlockSerializer(allow_null=True)
    teacher = TeacherBlockSerializer(allow_null=True)
    student = StudentBlockSerializer(allow_null=True)
    parent = ParentBlockSerializer(allow_null=True)
