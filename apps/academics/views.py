from django.db import transaction
from django.db.models import F
from drf_spectacular.utils import extend_schema
from rest_framework import mixins, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.access import (
    AudienceScopedMixin,
    OwnedObjectMixin,
    RolePermissionsMixin,
    SafeDestroyMixin,
    SchoolScopedMixin,
)
from apps.accounts.permissions import IsAdmin, IsStudent
from apps.assessments.models import Assessment, Submission

from . import openapi, rollover
from .aggregates import count_per, one_decimal, score_pct_per
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
from .openapi import child_filter
from .permissions import TeachesSubjectOrAdmin
from .rules import (
    child_param,
    children_enrolled_exists,
    children_of,
    current_session,
    enrolled_exists,
)
from .serializers import (
    AcademicSessionSerializer,
    ClassroomSerializer,
    CompletionSerializer,
    EnrollmentSerializer,
    LessonSerializer,
    RolloverSerializer,
    SubjectSerializer,
    TeachingAssignmentSerializer,
    TermSerializer,
)
from .services import create_session, make_term_current


class EveryoneReadsMixin(AudienceScopedMixin):
    """School-wide reference data (sessions, terms, subjects): every member may read it."""

    def scope_student(self, qs, user):
        return qs

    def scope_parent(self, qs, user):
        return qs


def id_param(params, name):
    """?name=<id> as an int, None if absent; anything else is a 400, not a database error."""
    value = params.get(name)
    if not value:
        return None
    if not value.isdigit():
        raise ValidationError({name: "Must be an ID (a whole number)."})
    return int(value)


def filter_by_params(qs, params, *names):
    """Apply ?name=<id> filters that the client sent, e.g. ?classroom=3&session=1."""
    for name in names:
        if (value := id_param(params, name)) is not None:
            qs = qs.filter(**{f"{name}_id": value})
    return qs


# --- the school year (admins set it up) -----------------------------------------------------


class AcademicSessionViewSet(
    RolePermissionsMixin,
    SchoolScopedMixin,
    EveryoneReadsMixin,
    SafeDestroyMixin,
    viewsets.ModelViewSet,
):
    """School years. Creating one creates its terms from the school's term names."""

    serializer_class = AcademicSessionSerializer
    queryset = AcademicSession.objects.prefetch_related("terms")
    write_permissions = (IsAdmin,)

    def perform_create(self, serializer):
        serializer.instance = create_session(self.request.user.school, **serializer.validated_data)


class TermViewSet(
    RolePermissionsMixin,
    SchoolScopedMixin,
    EveryoneReadsMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    """Terms are created with their session; admins rename them, date them and pick the
    current one."""

    serializer_class = TermSerializer
    queryset = Term.objects.select_related("session")
    school_path = "session__school"
    write_permissions = (IsAdmin,)
    action_permissions = {"make_current": (IsAdmin,)}

    def get_queryset(self):
        qs = filter_by_params(super().get_queryset(), self.request.query_params, "session")
        if self.request.query_params.get("current") in {"1", "true", "True"}:
            qs = qs.filter(is_current=True)
        return qs

    @action(detail=True, methods=["post"], url_path="make-current")
    def make_current(self, request, pk=None):
        term = make_term_current(self.get_object())
        return Response(TermSerializer(term, context=self.get_serializer_context()).data)


class SubjectViewSet(
    RolePermissionsMixin,
    SchoolScopedMixin,
    EveryoneReadsMixin,
    SafeDestroyMixin,
    viewsets.ModelViewSet,
):
    serializer_class = SubjectSerializer
    search_fields = ["name"]
    ordering_fields = ["name"]
    queryset = Subject.objects.order_by("name")
    write_permissions = (IsAdmin,)


@child_filter
class ClassroomViewSet(
    RolePermissionsMixin,
    SchoolScopedMixin,
    AudienceScopedMixin,
    SafeDestroyMixin,
    viewsets.ModelViewSet,
):
    """Class arms (JSS2A). Admins manage them and pick form teachers."""

    serializer_class = ClassroomSerializer
    search_fields = ["arm", "level__name", "form_teacher__first_name", "form_teacher__last_name"]
    ordering_fields = ["level__order", "arm", "created_at"]
    queryset = Classroom.objects.select_related("level", "form_teacher")
    write_permissions = (IsAdmin,)

    def get_queryset(self):
        return filter_by_params(super().get_queryset(), self.request.query_params, "level")

    def scope_student(self, qs, user):
        # the classes they have been in, any session
        return qs.filter(enrollments__student=user).distinct()

    def scope_parent(self, qs, user):
        # the classes their children have been in (?child= for one of them)
        child = child_param(self.request)
        lookup = {"enrollments__student__guardian_links__parent": user}
        if child is not None:
            lookup["enrollments__student_id"] = child
        return qs.filter(**lookup).distinct()


@child_filter
class TeachingAssignmentViewSet(
    RolePermissionsMixin, SchoolScopedMixin, AudienceScopedMixin, viewsets.ModelViewSet
):
    """Who teaches which subject to which class, per session. ?mine=true for your own."""

    serializer_class = TeachingAssignmentSerializer
    search_fields = ["subject__name", "teacher__first_name", "teacher__last_name"]
    ordering_fields = ["classroom__level__order", "subject__name", "teacher__last_name"]
    queryset = TeachingAssignment.objects.select_related(
        "session", "classroom__level", "subject", "teacher"
    ).order_by("classroom__level__order", "classroom__arm", "subject__name")
    school_path = "classroom__school"
    write_permissions = (IsAdmin,)

    def get_queryset(self):
        params = self.request.query_params
        qs = filter_by_params(super().get_queryset(), params, "session", "classroom", "teacher")
        if params.get("mine") in {"1", "true", "True"}:
            qs = qs.filter(teacher=self.request.user)
        return qs

    def scope_student(self, qs, user):
        # who teaches them: their classes, in those sessions
        return qs.filter(enrolled_exists(user, session_field="session"))

    def scope_parent(self, qs, user):
        return qs.filter(
            children_enrolled_exists(user, child=child_param(self.request), session_field="session")
        )


@child_filter
class EnrollmentViewSet(
    RolePermissionsMixin, SchoolScopedMixin, AudienceScopedMixin, viewsets.ModelViewSet
):
    """Which class each student is in, per session (one class per session)."""

    serializer_class = EnrollmentSerializer
    search_fields = [
        "student__first_name",
        "student__last_name",
        "student__username",
        "student__admission_number",
    ]
    ordering_fields = [
        "created_at",
        "student__last_name",
        "student__first_name",
        "student__admission_number",
    ]
    queryset = Enrollment.objects.select_related("session", "classroom__level", "student").order_by(
        "-created_at"
    )
    school_path = "classroom__school"
    write_permissions = (IsAdmin,)

    def get_queryset(self):
        return filter_by_params(
            super().get_queryset(), self.request.query_params, "session", "classroom"
        )

    def scope_student(self, qs, user):
        return qs.filter(student=user)

    def scope_parent(self, qs, user):
        return qs.filter(**children_of(user, child_param(self.request)))


# --- learning (teachers post for what they teach) -------------------------------------------


@child_filter
class LessonViewSet(
    RolePermissionsMixin,
    SchoolScopedMixin,
    AudienceScopedMixin,
    OwnedObjectMixin,
    viewsets.ModelViewSet,
):
    serializer_class = LessonSerializer
    search_fields = ["title", "content"]
    ordering_fields = ["created_at", "title"]
    queryset = Lesson.objects.select_related(
        "classroom__level", "subject", "term", "created_by"
    ).order_by("-created_at")
    school_path = "classroom__school"
    action_permissions = {"complete": (IsStudent,)}
    write_object_permissions = (TeachesSubjectOrAdmin,)

    def get_queryset(self):
        return filter_by_params(
            super().get_queryset(), self.request.query_params, "classroom", "subject", "term"
        )

    def scope_student(self, qs, user):
        return qs.filter(enrolled_exists(user))

    def scope_parent(self, qs, user):
        return qs.filter(children_enrolled_exists(user, child=child_param(self.request)))

    @action(detail=True, methods=["post"])
    def complete(self, request, pk=None):
        lesson = self.get_object()
        completion, _created = Completion.objects.get_or_create(lesson=lesson, student=request.user)
        return Response(CompletionSerializer(completion).data, status=201 if _created else 200)


class ProgressView(APIView):
    """Progress for one session (default: the current one, or ?session=<id>).

    Students get their own class; teachers the classes they teach or form-teach; admins every
    class (or ?classroom=<id>).
    """

    @extend_schema(
        parameters=[openapi.ProgressQuerySerializer], responses=openapi.ProgressSerializer
    )
    def get(self, request):
        user = request.user
        school_id = user.school_id
        session_id = id_param(request.query_params, "session")
        session = (
            AcademicSession.objects.filter(school_id=school_id, pk=session_id).first()
            if session_id
            else current_session(school_id)
        )
        if session is None:
            return Response({"session": None, "classrooms": []})

        classrooms = Classroom.objects.filter(school_id=school_id).select_related("level")
        if user.role == "student":
            classrooms = classrooms.filter(enrollments__student=user, enrollments__session=session)
        elif user.role == "teacher":
            classrooms = classrooms.filter(
                pk__in=TeachingAssignment.objects.filter(teacher=user, session=session).values(
                    "classroom"
                )
            ) | classrooms.filter(form_teacher=user)
        elif user.role != "admin":
            classrooms = classrooms.none()
        if (classroom_id := id_param(request.query_params, "classroom")) is not None:
            classrooms = classrooms.filter(pk=classroom_id)

        mine = {"student": user} if user.role == "student" else {}
        in_session = {"term__session": session}
        quizzes = Assessment.objects.filter(**in_session, type=Assessment.Type.QUIZ)
        # quiz submissions in this session; a student sees just their own
        quiz_work = Submission.objects.filter(
            assessment__term__session=session, assessment__type=Assessment.Type.QUIZ, **mine
        )
        classrooms = classrooms.distinct().annotate(
            n_students=count_per(Enrollment.objects.filter(session=session), "classroom"),
            n_lessons=count_per(Lesson.objects.filter(**in_session), "classroom"),
            # completions by students enrolled in the class that session
            n_completed=count_per(
                Completion.objects.filter(
                    lesson__term__session=session,
                    student__enrollments__session=session,
                    student__enrollments__classroom=F("lesson__classroom"),
                    **mine,
                ),
                "lesson__classroom",
            ),
            n_quizzes=count_per(quizzes, "classroom"),
            n_submitted=count_per(quiz_work, "assessment__classroom"),
            avg_pct=score_pct_per(quiz_work, "assessment__classroom"),
        )
        data = [
            {
                "classroom": {"id": c.pk, "name": c.name},
                "students": c.n_students,
                "lessons": {"total": c.n_lessons, "completed": c.n_completed},
                "quizzes": {
                    "total": c.n_quizzes,
                    "submitted": c.n_submitted,
                    "avg_score_pct": one_decimal(c.avg_pct),
                },
            }
            for c in classrooms
        ]
        return Response({"session": {"id": session.pk, "name": session.name}, "classrooms": data})


class RolloverView(APIView):
    """POST: move the school into the next session (admin).

    Without commit (the default) nothing is written: every student enrolled in from_session gets
    a planned action and class (promote to the same arm one level up, graduate from the final
    level), shown with their latest published average, plus any terms still unpublished. Send
    decisions to repeat, move, graduate or remove particular students. With commit=true and no
    errors, the new enrollments (and, by default, teaching assignments) are created at once.
    Students already enrolled in to_session are left alone, so it can be run again.
    """

    permission_classes = [IsAdmin]

    @extend_schema(
        request=RolloverSerializer,
        responses={200: openapi.RolloverResultSerializer, 400: openapi.RolloverResultSerializer},
    )
    def post(self, request):
        serializer = RolloverSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        source, target = data["from_session"], data["to_session"]
        with transaction.atomic():
            # one rollover into a session at a time: a second one waits, then finds these
            # students already enrolled
            AcademicSession.objects.select_for_update().get(pk=target.pk)
            plan = rollover.plan_rollover(
                request.user.school,
                source,
                target,
                data["decisions"],
                data["copy_teaching_assignments"],
            )
            commit = data["commit"] and plan.valid
            if commit:
                rollover.apply_rollover(plan, target, data["make_current"])
        body = rollover.report(plan, source, target, committed=commit)
        return Response(body, status=400 if data["commit"] and not plan.valid else 200)
