from rest_framework.response import Response
from rest_framework.views import APIView

from apps.academics.models import Classroom, Lesson
from apps.accounts.models import User
from apps.accounts.permissions import IsAdmin
from apps.assessments.models import Assessment, Submission
from apps.sessions.models import StudySession


class StatsView(APIView):
    """Counts and per-classroom breakdown for the admin's own school. Admin only."""

    permission_classes = [IsAdmin]

    def get(self, request):
        school_id = request.user.school_id
        in_school = {"classroom__school_id": school_id}
        submissions = Submission.objects.filter(assessment__classroom__school_id=school_id)
        scored = [
            s
            for s in submissions.select_related("assessment")
            if s.score is not None and s.assessment.max_points
        ]
        users = User.objects.filter(school_id=school_id)
        counts = {
            "students": users.filter(role=User.Role.STUDENT).count(),
            "teachers": users.filter(role=User.Role.TEACHER).count(),
            "parents": users.filter(role=User.Role.PARENT).count(),
            "classrooms": Classroom.objects.filter(school_id=school_id).count(),
            "lessons": Lesson.objects.filter(**in_school).count(),
            "assessments": Assessment.objects.filter(**in_school).count(),
            "submissions": submissions.count(),
            "sessions": StudySession.objects.filter(**in_school).count(),
        }
        classrooms = []
        for c in Classroom.objects.filter(school_id=school_id).prefetch_related("enrollments"):
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
