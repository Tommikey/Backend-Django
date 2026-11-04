from django.db.models import Q
from django.utils import timezone
from rest_framework import mixins, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.status import HTTP_409_CONFLICT

from apps.academics.permissions import TeachesSubjectOrAdmin
from apps.academics.rules import enrolled_exists, teaching_exists
from apps.academics.views import filter_by_params
from apps.accounts.access import (
    AudienceScopedMixin,
    OwnedObjectMixin,
    RolePermissionsMixin,
    SchoolScopedMixin,
)
from apps.accounts.permissions import IsStudent

from .models import Answer, Assessment, Submission
from .serializers import (
    AssessmentSerializer,
    AssessmentStudentSerializer,
    GradeSerializer,
    SubmissionSerializer,
    SubmitSerializer,
)


class AssessmentViewSet(
    RolePermissionsMixin,
    SchoolScopedMixin,
    AudienceScopedMixin,
    OwnedObjectMixin,
    viewsets.ModelViewSet,
):
    queryset = (
        Assessment.objects.select_related("classroom__level", "subject", "term", "created_by")
        .prefetch_related("questions__choices")
        .order_by("-created_at")
    )
    action_permissions = {"submit": (IsStudent,)}
    search_fields = ["title", "description"]
    ordering_fields = ["created_at", "due_at", "title"]
    write_object_permissions = (TeachesSubjectOrAdmin,)
    school_path = "classroom__school"

    def get_queryset(self):
        return filter_by_params(
            super().get_queryset(), self.request.query_params, "classroom", "subject", "term"
        )

    def scope_teacher(self, qs, user):
        # quizzes carry their answer keys: only for what the teacher teaches, or their form
        # class (the same rule as for reading submissions)
        return qs.filter(teaching_exists(user) | Q(classroom__form_teacher=user))

    def scope_student(self, qs, user):
        return qs.filter(enrolled_exists(user))

    def get_serializer_class(self):
        if self.action == "submit":
            return SubmitSerializer
        # getattr: the API schema generator asks with an anonymous user
        if getattr(self.request.user, "role", None) == "student":
            return AssessmentStudentSerializer
        return AssessmentSerializer

    @action(detail=True, methods=["post"])
    def submit(self, request, pk=None):
        assessment = self.get_object()
        if Submission.objects.filter(assessment=assessment, student=request.user).exists():
            return Response({"detail": "Already submitted."}, status=HTTP_409_CONFLICT)
        serializer = SubmitSerializer(data=request.data, context={"assessment": assessment})
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        answers = data.pop("answers", [])
        submission = Submission.objects.create(assessment=assessment, student=request.user, **data)
        Answer.objects.bulk_create([Answer(submission=submission, **answer) for answer in answers])
        if assessment.type == Assessment.Type.QUIZ:
            submission.score = sum(a["question"].points for a in answers if a["choice"].is_correct)
            submission.graded_at = timezone.now()
            submission.save(update_fields=["score", "graded_at"])
        return Response(SubmissionSerializer(submission).data, status=201)


class SubmissionViewSet(
    RolePermissionsMixin,
    SchoolScopedMixin,
    AudienceScopedMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    """Students see their own; teachers see work for what they teach (or their form class);
    only the subject's teacher (or an admin) grades."""

    serializer_class = SubmissionSerializer
    search_fields = [
        "student__first_name",
        "student__last_name",
        "student__username",
        "assessment__title",
    ]
    ordering_fields = ["submitted_at", "graded_at", "score", "student__last_name"]
    queryset = (
        Submission.objects.select_related("assessment__term", "student")
        .prefetch_related("answers__question", "answers__choice")
        .order_by("-submitted_at")
    )
    school_path = "assessment__classroom__school"
    write_object_permissions = (TeachesSubjectOrAdmin,)
    teaching_path = "assessment"  # TeachesSubjectOrAdmin reads class/subject/term from there

    def get_serializer_class(self):
        if self.action in {"update", "partial_update"}:
            return GradeSerializer
        return SubmissionSerializer

    def get_queryset(self):
        return filter_by_params(super().get_queryset(), self.request.query_params, "assessment")

    def scope_teacher(self, qs, user):
        return qs.filter(
            teaching_exists(user, prefix="assessment__")
            | Q(assessment__classroom__form_teacher=user)
        )

    def scope_student(self, qs, user):
        return qs.filter(student=user)

    def perform_update(self, serializer):
        serializer.save(graded_at=timezone.now())

    def partial_update(self, request, *args, **kwargs):
        # respond with the full submission, not the grade-only input serializer
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        return Response(SubmissionSerializer(instance).data)
