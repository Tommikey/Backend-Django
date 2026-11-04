from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied
from rest_framework.validators import UniqueTogetherValidator

from apps.accounts.access import SameSchoolSerializerMixin
from apps.accounts.models import User

from .models import (
    AcademicSession,
    Classroom,
    Completion,
    Enrollment,
    Lesson,
    Subject,
    TeachingAssignment,
    Term,
)
from .rules import current_session, current_term, teaches

# --- defaults: "now", unless the client says otherwise -------------------------------------


class CurrentSessionDefault:
    requires_context = True

    def __call__(self, field):
        session = current_session(field.context["request"].user.school_id)
        if session is None:
            raise serializers.ValidationError("Your school has no current session; give one.")
        return session


class CurrentTermDefault:
    requires_context = True

    def __call__(self, field):
        term = current_term(field.context["request"].user.school_id)
        if term is None:
            raise serializers.ValidationError("Your school has no current term; give one.")
        return term


def session_field():
    return serializers.PrimaryKeyRelatedField(
        queryset=AcademicSession.objects.all(), default=CurrentSessionDefault()
    )


def term_field():
    return serializers.PrimaryKeyRelatedField(
        queryset=Term.objects.all(), default=CurrentTermDefault()
    )


def must_have_role(user, role, message):
    if user.role != role:
        raise serializers.ValidationError(message)
    return user


class TeachingScopeSerializerMixin:
    """Teachers may only write items for a class + subject they teach in the term's session.

    Runs on create and update (the merged result is checked, so an item can't be moved into
    a class the teacher doesn't teach). Admins pass.
    """

    def validate(self, attrs):
        attrs = super().validate(attrs)
        user = self.context["request"].user
        if user.role == User.Role.ADMIN:
            return attrs

        def value(name):
            return attrs[name] if name in attrs else getattr(self.instance, name)

        classroom, subject, term = value("classroom"), value("subject"), value("term")
        if not teaches(user, classroom.pk, subject.pk, term.session_id):
            raise PermissionDenied(f"You don't teach {subject} to {classroom} in {term.session}.")
        return attrs


# --- the school year -------------------------------------------------------------------------


class TermSerializer(SameSchoolSerializerMixin, serializers.ModelSerializer):
    session_name = serializers.CharField(source="session.name", read_only=True)

    class Meta:
        model = Term
        fields = [
            "id",
            "session",
            "session_name",
            "name",
            "order",
            "starts_on",
            "ends_on",
            "is_current",
        ]
        # terms come from the session; only their name and dates are edited
        read_only_fields = ["session", "order", "is_current"]


class AcademicSessionSerializer(SameSchoolSerializerMixin, serializers.ModelSerializer):
    terms = TermSerializer(many=True, read_only=True)

    class Meta:
        model = AcademicSession
        fields = ["id", "name", "starts_on", "ends_on", "is_current", "terms"]
        read_only_fields = ["is_current"]

    def validate_name(self, value):
        return self.unique_in_school("name", value)

    def validate(self, attrs):
        starts = attrs.get("starts_on", getattr(self.instance, "starts_on", None))
        ends = attrs.get("ends_on", getattr(self.instance, "ends_on", None))
        if starts and ends and ends <= starts:
            raise serializers.ValidationError({"ends_on": "Must be after starts_on."})
        return attrs


class SubjectSerializer(SameSchoolSerializerMixin, serializers.ModelSerializer):
    class Meta:
        model = Subject
        fields = ["id", "name", "description"]

    def validate_name(self, value):
        return self.unique_in_school("name", value)


class ClassroomSerializer(SameSchoolSerializerMixin, serializers.ModelSerializer):
    name = serializers.CharField(read_only=True)
    level_name = serializers.CharField(source="level.name", read_only=True)
    form_teacher_name = serializers.CharField(
        source="form_teacher.display_name", read_only=True, default=None
    )

    class Meta:
        model = Classroom
        fields = [
            "id",
            "name",
            "level",
            "level_name",
            "arm",
            "form_teacher",
            "form_teacher_name",
            "description",
            "created_at",
        ]
        read_only_fields = ["created_at"]
        extra_kwargs = {"arm": {"default": ""}}  # a level with a single class has no arm
        validators = [
            UniqueTogetherValidator(
                queryset=Classroom.objects.all(),
                fields=["level", "arm"],
                message="This class already exists.",
            )
        ]

    def validate_arm(self, value):
        return value.strip()

    def validate_form_teacher(self, value):
        if value is not None:
            must_have_role(value, User.Role.TEACHER, "Form teachers must be teachers.")
        return value


class TeachingAssignmentSerializer(SameSchoolSerializerMixin, serializers.ModelSerializer):
    session = session_field()
    session_name = serializers.CharField(source="session.name", read_only=True)
    classroom_name = serializers.CharField(source="classroom.name", read_only=True)
    subject_name = serializers.CharField(source="subject.name", read_only=True)
    teacher_name = serializers.CharField(source="teacher.display_name", read_only=True)

    class Meta:
        model = TeachingAssignment
        fields = [
            "id",
            "session",
            "session_name",
            "classroom",
            "classroom_name",
            "subject",
            "subject_name",
            "teacher",
            "teacher_name",
            "created_at",
        ]
        read_only_fields = ["created_at"]
        validators = [
            UniqueTogetherValidator(
                queryset=TeachingAssignment.objects.all(),
                fields=["session", "classroom", "subject"],
                message="Someone already teaches this subject to this class this session.",
            )
        ]

    def validate_teacher(self, value):
        return must_have_role(value, User.Role.TEACHER, "Only teachers can be assigned.")


class EnrollmentSerializer(SameSchoolSerializerMixin, serializers.ModelSerializer):
    session = session_field()
    session_name = serializers.CharField(source="session.name", read_only=True)
    classroom_name = serializers.CharField(source="classroom.name", read_only=True)
    student_name = serializers.CharField(source="student.display_name", read_only=True)

    class Meta:
        model = Enrollment
        fields = [
            "id",
            "session",
            "session_name",
            "classroom",
            "classroom_name",
            "student",
            "student_name",
            "created_at",
        ]
        read_only_fields = ["created_at"]
        validators = [
            UniqueTogetherValidator(
                queryset=Enrollment.objects.all(),
                fields=["session", "student"],
                message="This student is already in a class this session.",
            )
        ]

    def validate_student(self, value):
        return must_have_role(value, User.Role.STUDENT, "Only students can be enrolled.")


# --- learning ----------------------------------------------------------------------------------


class LessonSerializer(
    TeachingScopeSerializerMixin, SameSchoolSerializerMixin, serializers.ModelSerializer
):
    term = term_field()
    term_name = serializers.CharField(source="term.name", read_only=True)
    classroom_name = serializers.CharField(source="classroom.name", read_only=True)
    subject_name = serializers.CharField(source="subject.name", read_only=True)
    created_by_name = serializers.CharField(
        source="created_by.display_name", read_only=True, default=None
    )

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
            "term",
            "term_name",
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
