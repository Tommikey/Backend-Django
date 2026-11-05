from django.db.models import Q
from django.utils import timezone
from rest_framework import mixins, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.status import HTTP_409_CONFLICT

from apps.academics.files import download
from apps.academics.openapi import DOWNLOAD, child_filter
from apps.academics.permissions import TeachesSubjectOrAdmin
from apps.academics.rules import (
    child_param,
    children_enrolled_exists,
    children_of,
    enrolled_exists,
    teaching_exists,
)
from apps.academics.views import filter_by_params
from apps.accounts.access import (
    AudienceScopedMixin,
    OwnedObjectMixin,
    RolePermissionsMixin,
    SchoolScopedMixin,
)
from apps.accounts.permissions import IsStudent
from apps.audit.log import AuditedMixin, ref
from apps.notifications import events

from .models import Answer, Assessment, Submission
from .serializers import (
    AssessmentSerializer,
    AssessmentStudentSerializer,
    GradeSerializer,
    SubmissionSerializer,
    SubmitSerializer,
)


@child_filter
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

    def scope_parent(self, qs, user):
        return qs.filter(children_enrolled_exists(user, child=child_param(self.request)))

    def get_serializer_class(self):
        if self.action == "submit":
            return SubmitSerializer
        # no answer keys for students or parents (getattr: the schema generator is anonymous)
        if getattr(self.request.user, "role", None) in {"student", "parent"}:
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

    def perform_create(self, serializer):
        super().perform_create(serializer)
        events.work_set(serializer.instance)


@child_filter
class SubmissionViewSet(
    AuditedMixin,
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
        "student__admission_number",
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
    audit_fields = ("score",)

    def audit_name(self, submission):
        return "submission"

    def audit_label(self, submission):
        return f"{submission.student.display_name}: {submission.assessment.title}"

    def audit_context(self, submission):
        assessment = submission.assessment
        return {
            "student": ref(submission.student),
            "classroom": ref(assessment.classroom),
            "subject": ref(assessment.subject),
            "term": ref(assessment.term),
        }

    def get_serializer_class(self):
        if self.action in {"update", "partial_update"}:
            return GradeSerializer
        return SubmissionSerializer

    @DOWNLOAD
    @action(detail=True, methods=["get"], url_path="file", url_name="file")
    def download_file(self, request, pk=None):
        """The submitted file: for the student, their parents, the subject's teacher, the
        form teacher and admins (whoever can see the submission)."""
        return download(self.get_object())

    def get_queryset(self):
        return filter_by_params(super().get_queryset(), self.request.query_params, "assessment")

    def scope_teacher(self, qs, user):
        return qs.filter(
            teaching_exists(user, prefix="assessment__")
            | Q(assessment__classroom__form_teacher=user)
        )

    def scope_student(self, qs, user):
        return qs.filter(student=user)

    def scope_parent(self, qs, user):
        return qs.filter(**children_of(user, child_param(self.request)))

    def perform_update(self, serializer):
        super().perform_update(serializer, graded_at=timezone.now())

    def partial_update(self, request, *args, **kwargs):
        # respond with the full submission, not the grade-only input serializer
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        return Response(SubmissionSerializer(instance).data)
