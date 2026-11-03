from rest_framework.response import Response
from rest_framework.views import APIView

from apps.academics.models import Classroom, Lesson
from apps.accounts.models import User
from apps.accounts.permissions import IsAdmin
from apps.assessments.models import Assessment, Submission
from apps.sessions.models import StudySession


class StatsView(APIView):
    """School-wide counts and per-classroom breakdown. Admin only."""

    permission_classes = [IsAdmin]

    def get(self, request):
        scored = [
            s
            for s in Submission.objects.select_related("assessment")
            if s.score is not None and s.assessment.max_points
        ]
        counts = {
            "students": User.objects.filter(role=User.Role.STUDENT).count(),
            "teachers": User.objects.filter(role=User.Role.TEACHER).count(),
            "classrooms": Classroom.objects.count(),
            "lessons": Lesson.objects.count(),
            "assessments": Assessment.objects.count(),
            "submissions": Submission.objects.count(),
            "sessions": StudySession.objects.count(),
        }
        classrooms = []
        for c in Classroom.objects.prefetch_related("enrollments"):
            class_scores = [s for s in scored if s.assessment.classroom_id == c.pk]
            classrooms.append(
                {
                    "id": c.pk,
                    "name": c.name,
                    "students": c.enrollments.count(),
                    "lessons": c.lessons.count(),
                    "assessments": c.assessments.count(),
                    "sessions": c.study_sessions.count(),
                    "avg_score_pct": round(
                        sum(s.score / s.assessment.max_points * 100 for s in class_scores)
                        / len(class_scores),
                        1,
                    )
                    if class_scores
                    else None,
                }
            )
        return Response({"counts": counts, "classrooms": classrooms})
