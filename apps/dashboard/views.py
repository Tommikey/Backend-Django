from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.academics.rules import current_term
from apps.accounts.models import User

from . import openapi, services


class DashboardView(APIView):
    """GET: what you should see first, for your role, in the current term.

    Admin: people, today's missing registers, the term's results status. Teacher: today's
    registers for your form classes, work to grade, your next live classes. Student: work due,
    next live classes, attendance, latest report card. Parent: the same per child, in brief.
    Only the block for your role is present; the others are null.
    """

    @extend_schema(responses=openapi.DashboardSerializer)
    def get(self, request):
        user = request.user
        term = current_term(user.school_id) if user.school_id else None
        today = user.school.today() if user.school_id else timezone.localdate()
        blocks = {
            User.Role.ADMIN: ("admin", lambda: services.admin_block(user, term, today)),
            User.Role.TEACHER: ("teacher", lambda: services.teacher_block(user, term, today)),
            User.Role.STUDENT: ("student", lambda: services.student_block(user, term)),
            User.Role.PARENT: ("parent", lambda: services.parent_block(user, term)),
        }
        data = {
            "role": user.role,
            "today": today,
            "term": services.term_ref(term) if term else None,
            "admin": None,
            "teacher": None,
            "student": None,
            "parent": None,
        }
        if user.school_id and user.role in blocks:
            key, build = blocks[user.role]
            data[key] = build()
        return Response(data)
