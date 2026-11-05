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

    def validate(self, attrs):
        term = self.instance
        starts = attrs.get("starts_on", term.starts_on if term else None)
        ends = attrs.get("ends_on", term.ends_on if term else None)
        if starts and ends and ends <= starts:
            raise serializers.ValidationError({"ends_on": "Must be after starts_on."})
        session = term.session if term else None
        if session is not None:
            if session.starts_on and starts and starts < session.starts_on:
                raise serializers.ValidationError(
                    {"starts_on": f"The session starts on {session.starts_on}."}
                )
            if session.ends_on and ends and ends > session.ends_on:
                raise serializers.ValidationError(
                    {"ends_on": f"The session ends on {session.ends_on}."}
                )
        return attrs


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
    student_admission_number = serializers.CharField(
        source="student.admission_number", read_only=True
    )

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
            "student_admission_number",
            "outcome",
            "created_at",
        ]
        read_only_fields = ["outcome", "created_at"]
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


# --- moving to the next session --------------------------------------------------------------


class RolloverDecisionSerializer(serializers.Serializer):
    student = serializers.PrimaryKeyRelatedField(queryset=User.objects.all())
    action = serializers.ChoiceField(choices=["promote", "repeat", "move", "graduate", "leave"])
    classroom = serializers.PrimaryKeyRelatedField(
        queryset=Classroom.objects.all(),
        required=False,
        allow_null=True,
        help_text="Where they go (required for move; overrides the default for promote/repeat)",
    )


class RolloverSerializer(SameSchoolSerializerMixin, serializers.Serializer):
    from_session = session_field()
    to_session = serializers.PrimaryKeyRelatedField(queryset=AcademicSession.objects.all())
    decisions = RolloverDecisionSerializer(many=True, required=False, default=list)
    copy_teaching_assignments = serializers.BooleanField(default=True)
    make_current = serializers.BooleanField(
        default=False, help_text="Switch the school to the new session's first term"
    )
    commit = serializers.BooleanField(default=False, help_text="false: preview only")

    def validate(self, attrs):
        source, target = attrs["from_session"], attrs["to_session"]
        if source == target:
            raise serializers.ValidationError(
                {
                    "to_session": f"This is the session students are coming from ({source}). "
                    "from_session defaults to the current session; give it explicitly after "
                    "switching to the new one."
                }
            )
        school_id = self.context["request"].user.school_id
        enrolled = set(
            Enrollment.objects.filter(session=source).values_list("student_id", flat=True)
        )
        decisions, errors = {}, []
        for i, d in enumerate(attrs["decisions"], 1):
            student, classroom = d["student"], d.get("classroom")
            # nested IDs aren't limited to the school by the mixin: check them here
            if student.school_id != school_id or student.pk not in enrolled:
                errors.append(f"Decision {i}: student {student.pk} isn't in a class in {source}.")
            elif student.pk in decisions:
                errors.append(f"Decision {i}: student {student.pk} given twice.")
            if classroom is not None and classroom.school_id != school_id:
                errors.append(f"Decision {i}: unknown classroom {classroom.pk}.")
            decisions[student.pk] = {"action": d["action"], "classroom": classroom}
        if errors:
            raise serializers.ValidationError({"decisions": errors})
        attrs["decisions"] = decisions
        return attrs
