"""Request bodies and query strings for the results endpoints (responses are built in
report_cards.py and views.py)."""

from rest_framework import serializers

from apps.academics.models import Classroom, Subject
from apps.academics.serializers import term_field
from apps.accounts.access import SameSchoolSerializerMixin
from apps.accounts.models import User
from apps.schools.models import AssessmentComponent


class ClassSubjectTermSerializer(SameSchoolSerializerMixin, serializers.Serializer):
    """?classroom=&subject=&term= (term defaults to the current one)."""

    classroom = serializers.PrimaryKeyRelatedField(queryset=Classroom.objects.all())
    subject = serializers.PrimaryKeyRelatedField(queryset=Subject.objects.all())
    term = term_field()


class ClassTermSerializer(SameSchoolSerializerMixin, serializers.Serializer):
    classroom = serializers.PrimaryKeyRelatedField(queryset=Classroom.objects.all())
    term = term_field()


class TermOnlySerializer(SameSchoolSerializerMixin, serializers.Serializer):
    term = term_field()


class StudentTermSerializer(SameSchoolSerializerMixin, serializers.Serializer):
    student = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.filter(role=User.Role.STUDENT), required=False
    )
    term = term_field()


class ScoreEntrySerializer(serializers.Serializer):
    # checked against the class and the school in ScoreSheetWriteSerializer.validate
    student = serializers.PrimaryKeyRelatedField(queryset=User.objects.all())
    component = serializers.PrimaryKeyRelatedField(queryset=AssessmentComponent.objects.all())
    value = serializers.DecimalField(
        max_digits=5, decimal_places=2, min_value=0, allow_null=True
    )  # null clears the score


class ScoreSheetWriteSerializer(ClassSubjectTermSerializer):
    scores = ScoreEntrySerializer(many=True)

    def validate(self, attrs):
        classroom, term = attrs["classroom"], attrs["term"]
        in_class = set(
            classroom.enrollments.filter(session=term.session).values_list("student", flat=True)
        )
        errors, seen = [], set()
        for i, entry in enumerate(attrs["scores"]):
            student, component, value = entry["student"], entry["component"], entry["value"]
            where = f"Row {i + 1}"
            if student.pk not in in_class:
                errors.append(f"{where}: student {student.pk} is not in {classroom}.")
            # a component of another school, or of another session's split
            if (
                component.school_id != classroom.school_id
                or component.session_id != term.session_id
            ):
                errors.append(f"{where}: unknown component {component.pk}.")
            elif value is not None and value > component.max_score:
                errors.append(f"{where}: {component.name} is out of {component.max_score}.")
            if (student.pk, component.pk) in seen:
                errors.append(f"{where}: student {student.pk} {component.name} given twice.")
            seen.add((student.pk, component.pk))
        if errors:
            raise serializers.ValidationError({"scores": errors})
        return attrs


class CommentSerializer(StudentTermSerializer):
    student = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.filter(role=User.Role.STUDENT)
    )
    form_teacher_comment = serializers.CharField(required=False, allow_blank=True)
    principal_comment = serializers.CharField(required=False, allow_blank=True)

    def validate(self, attrs):
        if "form_teacher_comment" not in attrs and "principal_comment" not in attrs:
            raise serializers.ValidationError("Give form_teacher_comment or principal_comment.")
        return attrs
