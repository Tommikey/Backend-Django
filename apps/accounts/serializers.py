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

    def validate_username(self, value):
        clash = User.objects.filter(username__iexact=value)
        if self.instance is not None:
            clash = clash.exclude(pk=self.instance.pk)
        if clash.exists():
            raise serializers.ValidationError("This username is taken.")
        return value

    def validate(self, attrs):
        user = self.instance
        if user is None:
            if not attrs.get("password"):
                raise serializers.ValidationError({"password": "Required when creating a user."})
            return attrs
        # a role decides what a user's records mean (a student's marks, a teacher's classes),
        # so it is fixed at creation; make a new account for a different role
        if "role" in attrs and attrs["role"] != user.role:
            raise serializers.ValidationError(
                {"role": "A role can't be changed; create a new account instead."}
            )
        # only active admins edit users, so refusing self-deactivation always leaves one
        if attrs.get("is_active") is False and user == self.context["request"].user:
            raise serializers.ValidationError(
                {"is_active": "You can't deactivate your own account."}
            )
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
    parent_name = serializers.CharField(source="parent.display_name", read_only=True)
    student_name = serializers.CharField(source="student.display_name", read_only=True)

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
