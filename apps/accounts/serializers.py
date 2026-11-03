from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers

from .models import User


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["id", "username", "email", "first_name", "last_name", "role"]
        read_only_fields = ["username", "role"]


class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, style={"input_type": "password"})

    class Meta:
        model = User
        fields = ["id", "username", "email", "password", "first_name", "last_name", "role"]
        extra_kwargs = {"role": {"default": User.Role.STUDENT}}

    def validate_password(self, value):
        validate_password(value)
        return value

    def validate_role(self, value):
        if value not in {User.Role.STUDENT, User.Role.TEACHER}:
            raise serializers.ValidationError("Self-registration is only for students or teachers.")
        return value

    def create(self, validated_data):
        return User.objects.create_user(**validated_data)
