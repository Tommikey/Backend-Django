"""Response shapes for the accounts endpoints' API docs."""

from rest_framework import serializers


class ImportRequestSerializer(serializers.Serializer):
    file = serializers.FileField(help_text="CSV; see GET imports/people/template/")
    commit = serializers.BooleanField(
        default=False, help_text="false (default): check and preview only; true: create everyone"
    )


class ImportSummarySerializer(serializers.Serializer):
    rows = serializers.IntegerField()
    students = serializers.IntegerField()
    teachers = serializers.IntegerField()
    parents = serializers.IntegerField()
    enrollments = serializers.IntegerField()
    parent_links = serializers.IntegerField()


class ImportRowErrorSerializer(serializers.Serializer):
    row = serializers.IntegerField(help_text="Spreadsheet row; the header is row 1")
    messages = serializers.ListField(child=serializers.CharField())


class ImportPersonSerializer(serializers.Serializer):
    row = serializers.IntegerField()
    id = serializers.IntegerField(allow_null=True, help_text="Null until committed")
    role = serializers.CharField()
    username = serializers.CharField(help_text="Generated from the name when left blank")
    admission_number = serializers.CharField()
    name = serializers.CharField()
    classroom = serializers.CharField(allow_null=True)
    children = serializers.ListField(child=serializers.CharField())
    activation_code = serializers.CharField(
        allow_null=True, help_text="Only after committing; shown once"
    )
    expires_at = serializers.DateTimeField(allow_null=True)


class ImportResultSerializer(serializers.Serializer):
    committed = serializers.BooleanField()
    valid = serializers.BooleanField()
    summary = ImportSummarySerializer()
    ignored_columns = serializers.ListField(child=serializers.CharField())
    errors = ImportRowErrorSerializer(many=True)
    people = ImportPersonSerializer(many=True)


class DetailSerializer(serializers.Serializer):
    detail = serializers.CharField()


class TokenPairSerializer(serializers.Serializer):
    access = serializers.CharField()
    refresh = serializers.CharField()
