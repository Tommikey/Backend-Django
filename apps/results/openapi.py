"""Response shapes for the results endpoints' API docs (the views build the JSON)."""

from rest_framework import serializers

from apps.academics.openapi import RefSerializer, StudentRefSerializer, TermRefSerializer
from apps.attendance.openapi import AttendanceSummarySerializer

DECIMAL = {"help_text": 'Decimal as a string, e.g. "77.50"'}


class ComponentSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    max_score = serializers.IntegerField()


class ScoreRowSerializer(serializers.Serializer):
    student = StudentRefSerializer()
    scores = serializers.DictField(
        child=serializers.CharField(allow_null=True),
        help_text="Component id -> mark (decimal string) or null if not entered",
    )
    total = serializers.CharField(allow_null=True, **DECIMAL)


class ScoreSheetSerializer(serializers.Serializer):
    classroom = RefSerializer()
    subject = RefSerializer()
    term = TermRefSerializer()
    published = serializers.BooleanField()
    can_edit = serializers.BooleanField()
    components = ComponentSerializer(many=True)
    rows = ScoreRowSerializer(many=True)


class CommentsResultSerializer(serializers.Serializer):
    student = serializers.IntegerField()
    term = serializers.IntegerField()
    form_teacher_comment = serializers.CharField()
    principal_comment = serializers.CharField()


class UnpublishResultSerializer(serializers.Serializer):
    term = serializers.IntegerField()
    published = serializers.BooleanField()


class CardScoreSerializer(serializers.Serializer):
    component = serializers.CharField()
    max_score = serializers.IntegerField()
    value = serializers.CharField(allow_null=True, **DECIMAL)


class CardSubjectSerializer(serializers.Serializer):
    subject = serializers.CharField()
    scores = CardScoreSerializer(many=True)
    total = serializers.CharField(**DECIMAL)
    grade = serializers.CharField()
    remark = serializers.CharField()
    grade_point = serializers.CharField(allow_null=True)
    class_average = serializers.CharField()
    class_highest = serializers.CharField()
    class_lowest = serializers.CharField()
    position = serializers.IntegerField(allow_null=True)


class CardSummarySerializer(serializers.Serializer):
    total = serializers.CharField(allow_null=True)
    average = serializers.CharField(allow_null=True)
    subjects_count = serializers.IntegerField()
    position = serializers.IntegerField(allow_null=True)
    out_of = serializers.IntegerField(allow_null=True)
    gpa = serializers.CharField(allow_null=True)


class SchoolRefSerializer(serializers.Serializer):
    name = serializers.CharField()
    system = serializers.CharField()


class TermNameSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()


class CardCommentsSerializer(serializers.Serializer):
    form_teacher = serializers.CharField()
    principal = serializers.CharField()


class GradeBandRefSerializer(serializers.Serializer):
    label = serializers.CharField()
    min_score = serializers.CharField()
    remark = serializers.CharField()
    grade_point = serializers.CharField(allow_null=True)


class ReportCardSerializer(serializers.Serializer):
    published = serializers.BooleanField(help_text="False: a live draft (staff only)")
    published_at = serializers.DateTimeField(allow_null=True)
    school = SchoolRefSerializer()
    student = StudentRefSerializer()
    classroom = RefSerializer()
    session = serializers.CharField()
    term = TermNameSerializer()
    form_teacher = serializers.CharField()
    subjects = CardSubjectSerializer(many=True)
    summary = CardSummarySerializer()
    attendance = AttendanceSummarySerializer(
        allow_null=True, help_text="Null when no register was taken in the term"
    )
    comments = CardCommentsSerializer()
    show_position = serializers.BooleanField()
    use_gpa = serializers.BooleanField()
    grading_scale = GradeBandRefSerializer(many=True)


class SubjectStatSerializer(serializers.Serializer):
    average = serializers.CharField()
    highest = serializers.CharField()
    lowest = serializers.CharField()


class BroadsheetRowSerializer(serializers.Serializer):
    student = StudentRefSerializer()
    totals = serializers.DictField(child=serializers.CharField(), help_text="Subject name -> total")
    total = serializers.CharField(allow_null=True)
    average = serializers.CharField(allow_null=True)
    gpa = serializers.CharField(allow_null=True)
    subjects_count = serializers.IntegerField()
    position = serializers.IntegerField(allow_null=True)
    out_of = serializers.IntegerField(allow_null=True)


class ClassResultsSerializer(serializers.Serializer):
    classroom = RefSerializer()
    term = TermRefSerializer()
    published = serializers.BooleanField()
    subjects = serializers.ListField(child=serializers.CharField())
    subject_stats = serializers.DictField(child=SubjectStatSerializer())
    rows = BroadsheetRowSerializer(many=True)
