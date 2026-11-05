"""Response shapes for the schools endpoints' API docs."""

from rest_framework import serializers

from apps.accounts.serializers import UserSerializer

from .serializers import AssessmentComponentSerializer, SchoolSerializer


class OnboardResultSerializer(serializers.Serializer):
    school = SchoolSerializer()
    admin = UserSerializer()


class SessionRefSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()


class ScoreSplitSerializer(serializers.Serializer):
    session = SessionRefSerializer(
        allow_null=True, help_text="Null: the school's default split (it has no session yet)"
    )
    components = AssessmentComponentSerializer(many=True)
