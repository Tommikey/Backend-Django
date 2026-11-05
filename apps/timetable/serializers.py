from rest_framework import serializers

from apps.academics.models import Classroom, Subject, TeachingAssignment
from apps.academics.serializers import session_field
from apps.accounts.access import SameSchoolSerializerMixin
from apps.accounts.models import User

from .models import DAYS, Period


class PeriodSerializer(SameSchoolSerializerMixin, serializers.ModelSerializer):
    class Meta:
        model = Period
        fields = ["id", "name", "starts_at", "ends_at", "is_break"]

    def validate_name(self, value):
        return self.unique_in_school("name", value)

    def validate(self, attrs):
        starts = attrs.get("starts_at", getattr(self.instance, "starts_at", None))
        ends = attrs.get("ends_at", getattr(self.instance, "ends_at", None))
        if starts and ends and ends <= starts:
            raise serializers.ValidationError({"ends_at": "A period must end after it starts."})
        school_id = self.context["request"].user.school_id
        overlapping = Period.objects.filter(
            school_id=school_id, starts_at__lt=ends, ends_at__gt=starts
        )
        if self.instance is not None:
            overlapping = overlapping.exclude(pk=self.instance.pk)
        if clash := overlapping.first():
            hours = f"{clash.starts_at:%H:%M}-{clash.ends_at:%H:%M}"
            raise serializers.ValidationError(
                {"starts_at": f"This overlaps {clash.name} ({hours})."}
            )
        return attrs


class ClassWeekQuerySerializer(SameSchoolSerializerMixin, serializers.Serializer):
    classroom = serializers.PrimaryKeyRelatedField(queryset=Classroom.objects.all())
    session = session_field()


class LessonInputSerializer(serializers.Serializer):
    day = serializers.ChoiceField(choices=list(DAYS.items()))
    period = serializers.IntegerField()
    subject = serializers.IntegerField()


class ClassWeekWriteSerializer(ClassWeekQuerySerializer):
    """The class's whole week; lessons left out are taken off the timetable."""

    lessons = LessonInputSerializer(many=True)

    def validate(self, attrs):
        classroom, session = attrs["classroom"], attrs["session"]
        school_id = self.context["request"].user.school_id
        periods = {p.pk: p for p in Period.objects.filter(school_id=school_id)}
        assignments = {
            a.subject_id: a
            for a in TeachingAssignment.objects.filter(
                classroom=classroom, session=session
            ).select_related("subject", "teacher")
        }
        subjects = dict(Subject.objects.filter(school_id=school_id).values_list("pk", "name"))
        errors, resolved, seen = {}, [], set()
        for i, item in enumerate(attrs["lessons"]):
            period = periods.get(item["period"])
            if period is None:
                errors[i] = {"period": "No such period."}
            elif period.is_break:
                errors[i] = {"period": f"{period.name} is a break."}
            elif (item["day"], period.pk) in seen:
                errors[i] = {"period": f"{DAYS[item['day']]}, {period.name} is given twice."}
            elif item["subject"] not in subjects:
                errors[i] = {"subject": "No such subject."}
            elif item["subject"] not in assignments:
                errors[i] = {
                    "subject": f"Nobody teaches {subjects[item['subject']]} to {classroom.name} "
                    f"in {session.name}; add a teaching assignment first."
                }
            else:
                seen.add((item["day"], period.pk))
                resolved.append((item["day"], period, assignments[item["subject"]]))
        if errors:
            raise serializers.ValidationError(
                {"lessons": [errors.get(i, {}) for i in range(len(attrs["lessons"]))]}
            )
        attrs["resolved"] = resolved
        return attrs


class TeacherWeekQuerySerializer(SameSchoolSerializerMixin, serializers.Serializer):
    teacher = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.filter(role=User.Role.TEACHER), required=False
    )
    session = session_field()
