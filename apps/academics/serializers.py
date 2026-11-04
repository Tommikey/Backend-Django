from rest_framework import serializers

from apps.accounts.access import SameSchoolSerializerMixin
from apps.accounts.models import User

from .models import Classroom, Completion, Enrollment, Lesson, Subject


class SubjectSerializer(SameSchoolSerializerMixin, serializers.ModelSerializer):
    class Meta:
        model = Subject
        fields = ["id", "name", "description"]

    def validate_name(self, value):
        return self.unique_in_school("name", value)


class ClassroomSerializer(SameSchoolSerializerMixin, serializers.ModelSerializer):
    created_by_name = serializers.CharField(source="created_by.get_full_name", read_only=True)

    class Meta:
        model = Classroom
        fields = ["id", "name", "description", "created_by", "created_by_name", "created_at"]
        read_only_fields = ["created_by", "created_at"]

    def validate_name(self, value):
        return self.unique_in_school("name", value)


class EnrollmentSerializer(SameSchoolSerializerMixin, serializers.ModelSerializer):
    classroom_name = serializers.CharField(source="classroom.name", read_only=True)
    student_name = serializers.CharField(source="student.get_full_name", read_only=True)

    class Meta:
        model = Enrollment
        fields = ["id", "classroom", "classroom_name", "student", "student_name", "created_at"]
        read_only_fields = ["created_at"]

    def validate_student(self, value):
        if value.role != User.Role.STUDENT:
            raise serializers.ValidationError("Only students can be enrolled.")
        return value


class LessonSerializer(SameSchoolSerializerMixin, serializers.ModelSerializer):
    classroom_name = serializers.CharField(source="classroom.name", read_only=True)
    subject_name = serializers.CharField(source="subject.name", read_only=True)
    created_by_name = serializers.CharField(source="created_by.get_full_name", read_only=True)

    class Meta:
        model = Lesson
        fields = [
            "id",
            "title",
            "content",
            "file",
            "classroom",
            "classroom_name",
            "subject",
            "subject_name",
            "created_by",
            "created_by_name",
            "created_at",
        ]
        read_only_fields = ["created_by", "created_at"]


class CompletionSerializer(serializers.ModelSerializer):
    lesson_title = serializers.CharField(source="lesson.title", read_only=True)

    class Meta:
        model = Completion
        fields = ["id", "lesson", "lesson_title", "completed_at"]
