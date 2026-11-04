from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.access import (
    OwnedObjectMixin,
    RolePermissionsMixin,
    StudentScopedQuerysetMixin,
)
from apps.accounts.permissions import IsStudent
from apps.assessments.models import Assessment, Submission

from .models import Classroom, Completion, Enrollment, Lesson, Subject
from .serializers import (
    ClassroomSerializer,
    CompletionSerializer,
    EnrollmentSerializer,
    LessonSerializer,
    SubjectSerializer,
)


class SubjectViewSet(RolePermissionsMixin, viewsets.ModelViewSet):
    serializer_class = SubjectSerializer
    queryset = Subject.objects.order_by("name")


class ClassroomViewSet(
    RolePermissionsMixin, OwnedObjectMixin, StudentScopedQuerysetMixin, viewsets.ModelViewSet
):
    serializer_class = ClassroomSerializer
    queryset = Classroom.objects.select_related("created_by").order_by("name")
    owner_scoped = True
    student_scope = "enrollments__student"


class EnrollmentViewSet(RolePermissionsMixin, StudentScopedQuerysetMixin, viewsets.ModelViewSet):
    serializer_class = EnrollmentSerializer
    queryset = Enrollment.objects.select_related("classroom", "student").order_by("-created_at")
    student_scope = "student"


class LessonViewSet(
    RolePermissionsMixin, OwnedObjectMixin, StudentScopedQuerysetMixin, viewsets.ModelViewSet
):
    serializer_class = LessonSerializer
    queryset = (
        Lesson.objects.select_related("classroom", "subject", "created_by").order_by("-created_at")
    )
    action_permissions = {"complete": (IsStudent,)}
    owner_scoped = True
    student_scope = "classroom__enrollments__student"

    @action(detail=True, methods=["post"])
    def complete(self, request, pk=None):
        lesson = self.get_object()
        completion, _created = Completion.objects.get_or_create(lesson=lesson, student=request.user)
        return Response(CompletionSerializer(completion).data, status=201 if _created else 200)


class ProgressView(APIView):
    """Own progress for students; class-level aggregates for teachers/admins (?classroom=<id>)."""

    def get(self, request):
        is_student = request.user.role == "student"
        if is_student:
            classrooms = Classroom.objects.filter(enrollments__student=request.user).distinct()
        else:
            qs = Classroom.objects.prefetch_related("enrollments")
            if classroom_id := request.query_params.get("classroom"):
                qs = qs.filter(pk=classroom_id)
            classrooms = qs

        data = []
        for classroom in classrooms:
            completions = Completion.objects.filter(lesson__classroom=classroom)
            submissions = Submission.objects.filter(
                assessment__classroom=classroom,
                assessment__type=Assessment.Type.QUIZ,
            )
            submissions = submissions.select_related("assessment")
            quizzes_total = Assessment.objects.filter(
                classroom=classroom, type=Assessment.Type.QUIZ
            ).count()
            if is_student:
                completions = completions.filter(student=request.user)
                submissions = submissions.filter(student=request.user)
            avg = None
            scored = [
                s for s in submissions if s.score is not None and s.assessment.max_points
            ]
            if scored:
                avg = round(
                    sum(s.score / s.assessment.max_points * 100 for s in scored) / len(scored), 1
                )
            data.append(
                {
                    "classroom": {"id": classroom.pk, "name": classroom.name},
                    "students": classroom.enrollments.count(),
                    "lessons": {
                        "total": classroom.lessons.count(),
                        "completed": completions.count(),
                    },
                    "quizzes": {
                        "total": quizzes_total,
                        "submitted": submissions.count(),
                        "avg_score_pct": avg,
                    },
                }
            )
        return Response({"classrooms": data})
