"""Response shapes for the schools endpoints' API docs."""

from rest_framework import serializers

from apps.accounts.serializers import UserSerializer

from .serializers import SchoolSerializer


class OnboardResultSerializer(serializers.Serializer):
    school = SchoolSerializer()
    admin = UserSerializer()
