"""The attendance endpoints.

- register: the form teacher (or an admin) takes a class's register for a day
- summary: the class's attendance counts for a term, for the same people
- student: one student's attendance, also for the student and their linked parents

The register locks with the term's results: once a term is published its report cards print
attendance, so the marks behind them can't change until it's unpublished.
"""

from django.db import transaction
from drf_spectacular.utils import extend_schema
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.access import InUse
from apps.accounts.models import User
from apps.results.access import can_read_published_card, can_review_class
from apps.results.serializers import ClassTermSerializer, StudentTermSerializer
from apps.results.services import class_students, enrollment_for, is_published, lock_term

from . import openapi
from .models import AttendanceRecord
from .serializers import RegisterQuerySerializer, RegisterWriteSerializer
from .services import class_attendance, register_dates


class AttendanceLocked(InUse):
    default_detail = "This term's results are published; unpublish it to change attendance."
    default_code = "published"


def validated(serializer_class, request, data):
    serializer = serializer_class(data=data, context={"request": request})
    serializer.is_valid(raise_exception=True)
    return serializer.validated_data


def check_can_take(user, classroom):
    if not can_review_class(user, classroom):
        raise PermissionDenied("Only the form teacher or an admin takes this class's register.")


def student_ref(student):
    return {"id": student.pk, "name": student.display_name}


def term_ref(term):
    return {"id": term.pk, "name": term.name, "session": term.session.name}


class RegisterView(APIView):
    """One class's register for one day.

    GET ?classroom=&date=&term=   PUT {classroom, date?, term?, marks: [{student, status,
    note?}]} with status present | late | absent | excused, or null to clear. Students left
    out of ``marks`` keep whatever they had.
    """

    @extend_schema(parameters=[RegisterQuerySerializer], responses=openapi.RegisterSerializer)
    def get(self, request):
        data = validated(RegisterQuerySerializer, request, request.query_params)
        check_can_take(request.user, data["classroom"])
        return Response(self.register(**data))

    @extend_schema(request=RegisterWriteSerializer, responses=openapi.RegisterSerializer)
    @transaction.atomic
    def put(self, request):
        data = validated(RegisterWriteSerializer, request, request.data)
        classroom, date, term = data["classroom"], data["date"], data["term"]
        check_can_take(request.user, classroom)
        lock_term(term)
        if is_published(term):
            raise AttendanceLocked()

        students = [mark["student"] for mark in data["marks"]]
        elsewhere = AttendanceRecord.objects.filter(student__in=students, date=date).exclude(
            term=term
        )
        if elsewhere.exists():
            raise ValidationError({"date": f"{date} is already recorded in another term."})

        for mark in data["marks"]:
            key = {"student": mark["student"], "date": date}
            if mark["status"] is None:
                AttendanceRecord.objects.filter(**key, term=term).delete()
            else:
                AttendanceRecord.objects.update_or_create(
                    **key,
                    defaults={
                        "classroom": classroom,
                        "term": term,
                        "status": mark["status"],
                        "note": mark["note"],
                        "marked_by": request.user,
                    },
                )
        return Response(self.register(classroom, date, term))

    @staticmethod
    def register(classroom, date, term):
        students = class_students(classroom, term.session)
        marks = {
            record.student_id: record
            for record in AttendanceRecord.objects.filter(
                student__in=students, date=date, term=term
            )
        }
        rows = []
        for student in students:
            record = marks.get(student.pk)
            rows.append(
                {
                    "student": student_ref(student),
                    "status": record.status if record else None,
                    "note": record.note if record else "",
                }
            )
        return {
            "classroom": {"id": classroom.pk, "name": classroom.name},
            "term": term_ref(term),
            "date": date,
            "taken": bool(marks),
            "can_edit": not is_published(term),
            "rows": rows,
        }


class ClassSummaryView(APIView):
    """GET ?classroom=&term=: every student's attendance counts for the term, plus the days
    the register was taken."""

    @extend_schema(parameters=[ClassTermSerializer], responses=openapi.ClassSummarySerializer)
    def get(self, request):
        data = validated(ClassTermSerializer, request, request.query_params)
        classroom, term = data["classroom"], data["term"]
        check_can_take(request.user, classroom)
        students = class_students(classroom, term.session)
        summaries = class_attendance(classroom, term, students)
        return Response(
            {
                "classroom": {"id": classroom.pk, "name": classroom.name},
                "term": term_ref(term),
                "register_dates": register_dates(classroom, term),
                "rows": [{"student": student_ref(s), **summaries[s.pk]} for s in students],
            }
        )


class StudentAttendanceView(APIView):
    """GET ?student=&term= (students may omit student): one student's counts and day-by-day
    marks for the term. For the student, their parents, the form teacher and admins.
    """

    @extend_schema(
        parameters=[StudentTermSerializer], responses=openapi.StudentAttendanceSerializer
    )
    def get(self, request):
        user = request.user
        data = validated(StudentTermSerializer, request, request.query_params)
        term = data["term"]
        student = data.get("student") or (user if user.role == User.Role.STUDENT else None)
        if student is None:
            raise NotFound("Say which student (?student=<id>).")
        marks = AttendanceRecord.objects.filter(student=student, term=term).order_by("date")
        # the student's class: their enrollment, or, if they have since left it, the class
        # their register was taken in
        enrollment = enrollment_for(student, term.session)
        if enrollment is not None:
            classroom = enrollment.classroom
        else:
            last = marks.select_related("classroom__level").last()
            classroom = last.classroom if last else None
        # same readers as a published report card; anyone else learns nothing about the student
        if classroom is None or not can_read_published_card(user, student, classroom):
            raise NotFound("No attendance for this student and term.")
        summary = class_attendance(classroom, term, [student])[student.pk]
        return Response(
            {
                "student": student_ref(student),
                "classroom": {"id": classroom.pk, "name": classroom.name},
                "term": term_ref(term),
                "summary": summary,
                "marks": [{"date": m.date, "status": m.status, "note": m.note} for m in marks],
            }
        )
