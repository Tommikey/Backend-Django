"""Response shapes for the attendance endpoints' API docs (the views build the JSON)."""

from rest_framework import serializers

from apps.academics.openapi import RefSerializer, TermRefSerializer

from .models import AttendanceRecord


class AttendanceSummarySerializer(serializers.Serializer):
    days_open = serializers.IntegerField(help_text="Days the class register was taken")
    present = serializers.IntegerField(help_text="Includes late")
    late = serializers.IntegerField()
    absent = serializers.IntegerField(help_text="Excludes excused")
    excused = serializers.IntegerField()
    unmarked = serializers.IntegerField(help_text="Register taken but this student not marked")


class RegisterRowSerializer(serializers.Serializer):
    student = RefSerializer()
    status = serializers.ChoiceField(choices=AttendanceRecord.Status.choices, allow_null=True)
    note = serializers.CharField()


class RegisterSerializer(serializers.Serializer):
    classroom = RefSerializer()
    term = TermRefSerializer()
    date = serializers.DateField()
    taken = serializers.BooleanField(help_text="At least one student is marked")
    can_edit = serializers.BooleanField(help_text="False once the term's results are published")
    rows = RegisterRowSerializer(many=True)


class SummaryRowSerializer(AttendanceSummarySerializer):
    student = RefSerializer()


class ClassSummarySerializer(serializers.Serializer):
    classroom = RefSerializer()
    term = TermRefSerializer()
    register_dates = serializers.ListField(child=serializers.DateField())
    rows = SummaryRowSerializer(many=True)


class MarkSerializer(serializers.Serializer):
    date = serializers.DateField()
    status = serializers.ChoiceField(choices=AttendanceRecord.Status.choices)
    note = serializers.CharField()


class StudentAttendanceSerializer(serializers.Serializer):
    student = RefSerializer()
    classroom = RefSerializer()
    term = TermRefSerializer()
    summary = AttendanceSummarySerializer()
    marks = MarkSerializer(many=True)
