from django.utils import timezone
from rest_framework import mixins, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.status import HTTP_409_CONFLICT

from apps.accounts.permissions import IsStudent, IsTeacherOrAdmin

from .models import Answer, Assessment, Submission
from .serializers import (
    AssessmentSerializer,
    AssessmentStudentSerializer,
    GradeSerializer,
    SubmissionSerializer,
    SubmitSerializer,
)


class AssessmentViewSet(viewsets.ModelViewSet):
    queryset = (
        Assessment.objects.select_related("classroom", "subject", "created_by")
        .prefetch_related("questions__choices")
        .order_by("-created_at")
    )

    def get_permissions(self):
        if self.action == "submit":
            return [IsStudent()]
        if self.action in {"create", "update", "partial_update", "destroy"}:
            return [IsTeacherOrAdmin()]
        return []

    def get_serializer_class(self):
        if self.action == "submit":
            return SubmitSerializer
        if self.request.user.role == "student":
            return AssessmentStudentSerializer
        return AssessmentSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user
        if user.role == "student":
            qs = qs.filter(classroom__enrollments__student=user).distinct()
        return qs

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    @action(detail=True, methods=["post"])
    def submit(self, request, pk=None):
        assessment = self.get_object()
        if Submission.objects.filter(assessment=assessment, student=request.user).exists():
            return Response({"detail": "Already submitted."}, status=HTTP_409_CONFLICT)
        serializer = SubmitSerializer(data=request.data, context={"assessment": assessment})
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        answers = data.pop("answers", [])
        submission = Submission.objects.create(
            assessment=assessment, student=request.user, **data
        )
        Answer.objects.bulk_create([Answer(submission=submission, **answer) for answer in answers])
        if assessment.type == Assessment.Type.QUIZ:
            submission.score = sum(
                a["question"].points for a in answers if a["choice"].is_correct
            )
            submission.graded_at = timezone.now()
            submission.save(update_fields=["score", "graded_at"])
        return Response(SubmissionSerializer(submission).data, status=201)


class SubmissionViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    serializer_class = SubmissionSerializer
    queryset = (
        Submission.objects.select_related("assessment", "student")
        .prefetch_related("answers__question", "answers__choice")
        .order_by("-submitted_at")
    )

    def get_permissions(self):
        if self.action in {"update", "partial_update"}:
            return [IsTeacherOrAdmin()]
        return []

    def get_serializer_class(self):
        if self.action in {"update", "partial_update"}:
            return GradeSerializer
        return SubmissionSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user
        if user.role == "student":
            qs = qs.filter(student=user)
        assessment_id = self.request.query_params.get("assessment")
        if assessment_id:
            qs = qs.filter(assessment_id=assessment_id)
        return qs

    def perform_update(self, serializer):
        serializer.save(graded_at=timezone.now())

    def partial_update(self, request, *args, **kwargs):
        # respond with the full submission, not the grade-only input serializer
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        return Response(SubmissionSerializer(instance).data)
