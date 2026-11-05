"""Request bodies and query strings for the attendance endpoints (responses are built in
views.py)."""

from rest_framework import serializers

from apps.academics.models import Classroom
from apps.academics.serializers import term_field
from apps.accounts.access import SameSchoolSerializerMixin
from apps.accounts.models import User

from .models import AttendanceRecord


class SchoolToday:
    """Default for a date field: today where the requesting user's school is."""

    requires_context = True

    def __call__(self, field):
        return field.context["request"].user.school.today()


class RegisterQuerySerializer(SameSchoolSerializerMixin, serializers.Serializer):
    """?classroom=&date=&term= (date defaults to today, term to the current one)."""

    classroom = serializers.PrimaryKeyRelatedField(queryset=Classroom.objects.all())
    date = serializers.DateField(default=SchoolToday())
    term = term_field()

    def validate(self, attrs):
        date, term = attrs["date"], attrs["term"]
        if date > self.context["request"].user.school.today():
            raise serializers.ValidationError({"date": "The register can't be taken ahead."})
        if (term.starts_on and date < term.starts_on) or (term.ends_on and date > term.ends_on):
            raise serializers.ValidationError({"date": f"{date} is outside {term}."})
        return attrs


class MarkSerializer(serializers.Serializer):
    # checked against the class in RegisterWriteSerializer.validate
    student = serializers.PrimaryKeyRelatedField(queryset=User.objects.all())
    status = serializers.ChoiceField(
        choices=AttendanceRecord.Status.choices, allow_null=True
    )  # null clears the mark
    note = serializers.CharField(max_length=200, required=False, allow_blank=True, default="")


class RegisterWriteSerializer(RegisterQuerySerializer):
    marks = MarkSerializer(many=True, allow_empty=False)

    def validate(self, attrs):
        attrs = super().validate(attrs)
        classroom, term = attrs["classroom"], attrs["term"]
        in_class = set(
            classroom.enrollments.filter(session=term.session).values_list("student", flat=True)
        )
        errors, seen = [], set()
        for i, mark in enumerate(attrs["marks"]):
            student = mark["student"]
            where = f"Row {i + 1}"
            if student.pk not in in_class:
                errors.append(f"{where}: student {student.pk} is not in {classroom}.")
            if student.pk in seen:
                errors.append(f"{where}: student {student.pk} given twice.")
            seen.add(student.pk)
        if errors:
            raise serializers.ValidationError({"marks": errors})
        return attrs
