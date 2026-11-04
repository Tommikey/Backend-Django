from rest_framework import mixins, viewsets
from rest_framework.decorators import action
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
from .permissions import TeachesSubjectOrAdmin
from .rules import current_session, enrolled_exists
from .serializers import (
    AcademicSessionSerializer,
    ClassroomSerializer,
    CompletionSerializer,
    EnrollmentSerializer,
    LessonSerializer,
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


def filter_by_params(qs, params, *names):
    """Apply ?name=<id> filters that the client sent, e.g. ?classroom=3&session=1."""
    for name in names:
        if value := params.get(name):
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
    queryset = Subject.objects.order_by("name")
    write_permissions = (IsAdmin,)


class ClassroomViewSet(
    RolePermissionsMixin,
    SchoolScopedMixin,
    AudienceScopedMixin,
    SafeDestroyMixin,
    viewsets.ModelViewSet,
):
    """Class arms (JSS2A). Admins manage them and pick form teachers."""

    serializer_class = ClassroomSerializer
    queryset = Classroom.objects.select_related("level", "form_teacher")
    write_permissions = (IsAdmin,)

    def get_queryset(self):
        return filter_by_params(super().get_queryset(), self.request.query_params, "level")

    def scope_student(self, qs, user):
        # the classes they have been in, any session
        return qs.filter(enrollments__student=user).distinct()


class TeachingAssignmentViewSet(
    RolePermissionsMixin, SchoolScopedMixin, AudienceScopedMixin, viewsets.ModelViewSet
):
    """Who teaches which subject to which class, per session. ?mine=true for your own."""

    serializer_class = TeachingAssignmentSerializer
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


class EnrollmentViewSet(
    RolePermissionsMixin, SchoolScopedMixin, AudienceScopedMixin, viewsets.ModelViewSet
):
    """Which class each student is in, per session (one class per session)."""

    serializer_class = EnrollmentSerializer
    queryset = Enrollment.objects.select_related(
        "session", "classroom__level", "student"
    ).order_by("-created_at")
    school_path = "classroom__school"
    write_permissions = (IsAdmin,)

    def get_queryset(self):
        return filter_by_params(
            super().get_queryset(), self.request.query_params, "session", "classroom"
        )

    def scope_student(self, qs, user):
        return qs.filter(student=user)


# --- learning (teachers post for what they teach) -------------------------------------------


class LessonViewSet(
    RolePermissionsMixin,
    SchoolScopedMixin,
    AudienceScopedMixin,
    OwnedObjectMixin,
    viewsets.ModelViewSet,
):
    serializer_class = LessonSerializer
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

    def get(self, request):
        user = request.user
        school_id = user.school_id
        session_id = request.query_params.get("session")
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
        if classroom_id := request.query_params.get("classroom"):
            classrooms = classrooms.filter(pk=classroom_id)

        data = [
            self.classroom_progress(classroom, session, user)
            for classroom in classrooms.distinct()
        ]
        return Response({"session": {"id": session.pk, "name": session.name}, "classrooms": data})

    @staticmethod
    def classroom_progress(classroom, session, user):
        in_session = {"classroom": classroom, "term__session": session}
        lessons = Lesson.objects.filter(**in_session)
        completions = Completion.objects.filter(
            lesson__in=lessons, student__enrollments__classroom=classroom,
            student__enrollments__session=session,
        )
        quizzes = Assessment.objects.filter(**in_session, type=Assessment.Type.QUIZ)
        submissions = Submission.objects.filter(assessment__in=quizzes).select_related(
            "assessment"
        )
        if user.role == "student":
            completions = completions.filter(student=user)
            submissions = submissions.filter(student=user)
        scored = [s for s in submissions if s.score is not None and s.assessment.max_points]
        avg = (
            round(sum(s.score / s.assessment.max_points * 100 for s in scored) / len(scored), 1)
            if scored
            else None
        )
        return {
            "classroom": {"id": classroom.pk, "name": classroom.name},
            "students": classroom.enrollments.filter(session=session).count(),
            "lessons": {"total": lessons.count(), "completed": completions.count()},
            "quizzes": {
                "total": quizzes.count(),
                "submitted": submissions.count(),
                "avg_score_pct": avg,
            },
        }
