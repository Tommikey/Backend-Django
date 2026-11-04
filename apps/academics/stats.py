from drf_spectacular.utils import extend_schema
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.academics.models import Classroom, Enrollment, Lesson
from apps.academics.rules import current_session
from apps.accounts.models import User
from apps.accounts.permissions import IsAdmin
from apps.assessments.models import Assessment, Submission
from apps.live_classes.models import LiveClass

from . import openapi
from .aggregates import count_per, one_decimal, score_pct_per


class StatsView(APIView):
    """Counts and per-classroom breakdown for the admin's own school. Admin only."""

    permission_classes = [IsAdmin]

    @extend_schema(responses=openapi.StatsSerializer)
    def get(self, request):
        school_id = request.user.school_id
        in_school = {"classroom__school_id": school_id}
        submissions = Submission.objects.filter(assessment__classroom__school_id=school_id)
        users = User.objects.filter(school_id=school_id)
        counts = {
            "students": users.filter(role=User.Role.STUDENT).count(),
            "teachers": users.filter(role=User.Role.TEACHER).count(),
            "parents": users.filter(role=User.Role.PARENT).count(),
            "classrooms": Classroom.objects.filter(school_id=school_id).count(),
            "lessons": Lesson.objects.filter(**in_school).count(),
            "assessments": Assessment.objects.filter(**in_school).count(),
            "submissions": submissions.count(),
            "live_classes": LiveClass.objects.filter(**in_school).count(),
        }
        session = current_session(school_id)
        classrooms = (
            Classroom.objects.filter(school_id=school_id)
            .select_related("level")
            .annotate(
                # students in the class this session
                n_students=count_per(Enrollment.objects.filter(session=session), "classroom"),
                n_lessons=count_per(Lesson.objects.all(), "classroom"),
                n_assessments=count_per(Assessment.objects.all(), "classroom"),
                n_live_classes=count_per(LiveClass.objects.all(), "classroom"),
                avg_pct=score_pct_per(Submission.objects.all(), "assessment__classroom"),
            )
        )
        return Response(
            {
                "counts": counts,
                "classrooms": [
                    {
                        "id": c.pk,
                        "name": c.name,
                        "students": c.n_students,
                        "lessons": c.n_lessons,
                        "assessments": c.n_assessments,
                        "live_classes": c.n_live_classes,
                        "avg_score_pct": one_decimal(c.avg_pct),
                    }
                    for c in classrooms
                ],
            }
        )
