from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers

from .access import SameSchoolSerializerMixin
from .models import Guardianship, User


class UserSerializer(serializers.ModelSerializer):
    """The logged-in user's own profile."""

    school_name = serializers.CharField(source="school.name", read_only=True, default=None)

    class Meta:
        model = User
        fields = [
            "id",
            "username",
            "email",
            "first_name",
            "last_name",
            "role",
            "school",
            "school_name",
        ]
        read_only_fields = ["username", "role", "school"]


class SchoolUserSerializer(serializers.ModelSerializer):
    """Users as managed by their school's admin. The school is set by the view, never sent."""

    password = serializers.CharField(
        write_only=True, required=False, style={"input_type": "password"}
    )

    class Meta:
        model = User
        fields = [
            "id",
            "username",
            "email",
            "first_name",
            "last_name",
            "role",
            "is_active",
            "password",
            "date_joined",
        ]
        read_only_fields = ["date_joined"]

    def validate_password(self, value):
        validate_password(value)
        return value

    def validate(self, attrs):
        if self.instance is None and not attrs.get("password"):
            raise serializers.ValidationError({"password": "Required when creating a user."})
        return attrs

    def create(self, validated_data):
        return User.objects.create_user(**validated_data)

    def update(self, instance, validated_data):
        password = validated_data.pop("password", None)
        user = super().update(instance, validated_data)
        if password:
            user.set_password(password)
            user.save(update_fields=["password"])
        return user


class GuardianshipSerializer(SameSchoolSerializerMixin, serializers.ModelSerializer):
    parent_name = serializers.CharField(source="parent.get_full_name", read_only=True)
    student_name = serializers.CharField(source="student.get_full_name", read_only=True)

    class Meta:
        model = Guardianship
        fields = [
            "id",
            "parent",
            "parent_name",
            "student",
            "student_name",
            "relationship",
            "created_at",
        ]
        read_only_fields = ["created_at"]

    def validate_parent(self, value):
        if value.role != User.Role.PARENT:
            raise serializers.ValidationError("Must be a parent account.")
        return value

    def validate_student(self, value):
        if value.role != User.Role.STUDENT:
            raise serializers.ValidationError("Must be a student account.")
        return value
