from django.db import IntegrityError, transaction
from drf_spectacular.utils import extend_schema
from rest_framework import viewsets
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.academics.models import Enrollment
from apps.accounts.access import (
    InUse,
    RolePermissionsMixin,
    SafeDestroyMixin,
    SchoolScopedMixin,
)
from apps.accounts.models import User
from apps.accounts.permissions import IsAdmin, IsTeacherOrAdmin
from apps.audit import log as audit
from apps.audit.log import AuditedMixin, ref

from . import openapi, services
from .models import DAYS, Period, Slot
from .serializers import (
    ClassWeekQuerySerializer,
    ClassWeekWriteSerializer,
    PeriodSerializer,
    TeacherWeekQuerySerializer,
)


def validated(serializer_class, request, data):
    serializer = serializer_class(data=data, context={"request": request})
    serializer.is_valid(raise_exception=True)
    return serializer.validated_data


class PeriodViewSet(
    AuditedMixin, RolePermissionsMixin, SchoolScopedMixin, SafeDestroyMixin, viewsets.ModelViewSet
):
    """The school day's periods and breaks, the same every day. Everyone reads; admins edit.
    A period used on a timetable can't be deleted (409)."""

    serializer_class = PeriodSerializer
    queryset = Period.objects.all()
    write_permissions = (IsAdmin,)
    audit_fields = ("name", "starts_at", "ends_at", "is_break")


def can_see_class(user, classroom, session):
    if user.role in (User.Role.ADMIN, User.Role.TEACHER):
        return True
    enrolled = Enrollment.objects.filter(classroom=classroom, session=session)
    if user.role == User.Role.STUDENT:
        return enrolled.filter(student=user).exists()
    if user.role == User.Role.PARENT:
        return enrolled.filter(student__guardian_links__parent=user).exists()
    return False


class ClassTimetableView(APIView):
    """A class's week. GET ?classroom=&session= (staff; the class's students and their
    parents). PUT {classroom, session?, lessons: [{day, period, subject}]} replaces the whole
    week (admins): the subject's teacher comes from the class's teaching assignment, and a
    teacher can't be in two classes in the same period."""

    @extend_schema(parameters=[ClassWeekQuerySerializer], responses=openapi.ClassWeekSerializer)
    def get(self, request):
        data = validated(ClassWeekQuerySerializer, request, request.query_params)
        classroom, session = data["classroom"], data["session"]
        if not can_see_class(request.user, classroom, session):
            raise NotFound("No timetable for you here.")
        return Response(self.week(request.user, classroom, session))

    @extend_schema(request=ClassWeekWriteSerializer, responses=openapi.ClassWeekSerializer)
    @transaction.atomic
    def put(self, request):
        if request.user.role != User.Role.ADMIN:
            raise PermissionDenied("Only admins edit the timetable.")
        data = validated(ClassWeekWriteSerializer, request, request.data)
        classroom, session, resolved = data["classroom"], data["session"], data["resolved"]
        wanted = [(a.teacher_id, day, period.pk) for day, period, a in resolved]
        if clashes := services.teacher_clashes(session, wanted, ignore_classroom=classroom):
            raise ValidationError({"lessons": [services.describe(s) for s in clashes]})

        before = self.summary(services.slots_for(classroom=classroom, session=session))
        Slot.objects.filter(classroom=classroom, session=session).delete()
        try:
            with transaction.atomic():
                Slot.objects.bulk_create(
                    Slot(assignment=a, session=session, classroom=classroom, day=day, period=period)
                    for day, period, a in resolved
                )
        except IntegrityError as exc:  # another admin saved this class at the same moment
            raise InUse("The timetable changed while you were editing; reload it.") from exc
        after = self.summary(services.slots_for(classroom=classroom, session=session))
        if before != after:
            audit.record(
                "timetable.replaced",
                school=classroom.school,
                request=request,
                label=f"{classroom.name} timetable, {session.name}",
                changes={"old": before, "new": after},
                context={"classroom": ref(classroom), "session": ref(session)},
            )
        return Response(self.week(request.user, classroom, session))

    @staticmethod
    def summary(slots):
        return sorted(f"{DAYS[s.day]} {s.period.name}: {s.assignment.subject.name}" for s in slots)

    @staticmethod
    def week(user, classroom, session):
        slots = list(services.slots_for(classroom=classroom, session=session))
        return {
            "classroom": {"id": classroom.pk, "name": classroom.name},
            "session": {"id": session.pk, "name": session.name},
            "can_edit": user.role == User.Role.ADMIN,
            **services.week(classroom.school, slots),
        }


class TeacherTimetableView(APIView):
    """GET ?teacher=&session=: a teacher's week across their classes (staff). Teachers get
    their own without ?teacher=."""

    permission_classes = [IsTeacherOrAdmin]

    @extend_schema(parameters=[TeacherWeekQuerySerializer], responses=openapi.TeacherWeekSerializer)
    def get(self, request):
        data = validated(TeacherWeekQuerySerializer, request, request.query_params)
        teacher = data.get("teacher") or request.user
        if teacher.role != User.Role.TEACHER:
            raise NotFound("Say which teacher (?teacher=<id>).")
        session = data["session"]
        slots = list(services.slots_for(assignment__teacher=teacher, session=session))
        return Response(
            {
                "teacher": {"id": teacher.pk, "name": teacher.display_name},
                "session": {"id": session.pk, "name": session.name},
                **services.week(teacher.school, slots, with_classroom=True, with_teacher=False),
            }
        )
