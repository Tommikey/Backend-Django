"""Response shapes for the accounts endpoints' API docs."""

from rest_framework import serializers


class TokenPairSerializer(serializers.Serializer):
    access = serializers.CharField()
    refresh = serializers.CharField()
