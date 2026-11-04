from django.db import transaction
from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.access import InUse
from apps.accounts.models import User
from apps.accounts.permissions import IsAdmin

from . import report_cards
from .access import (
    can_enter_scores,
    can_read_published_card,
    can_review_class,
    can_view_scores,
    is_admin,
    is_form_teacher,
)
from .models import Publication, Score, TermResult
from .serializers import (
    ClassSubjectTermSerializer,
    ClassTermSerializer,
    CommentSerializer,
    ScoreSheetWriteSerializer,
    StudentTermSerializer,
    TermOnlySerializer,
)
from .services import (
    class_students,
    compute_class_results,
    dec,
    enrollment_for,
    is_published,
    lock_term,
    publish_term,
    unpublish_term,
)


class TermPublished(InUse):
    default_detail = "This term's results are published; unpublish it to make changes."
    default_code = "published"


def validated(serializer_class, request, data):
    serializer = serializer_class(data=data, context={"request": request})
    serializer.is_valid(raise_exception=True)
    return serializer.validated_data


class ScoreSheetView(APIView):
    """One class's scores for one subject and term: students x components.

    GET ?classroom=&subject=&term=   PUT {classroom, subject, term?, scores: [{student,
    component, value}]} (value null clears). Only the subject's teacher (or an admin) edits,
    and only until the term is published.
    """

    def get(self, request):
        data = validated(ClassSubjectTermSerializer, request, request.query_params)
        if not can_view_scores(request.user, data["classroom"], data["subject"], data["term"]):
            raise PermissionDenied("You don't teach this subject to this class.")
        return Response(self.sheet(request.user, **data))

    @transaction.atomic
    def put(self, request):
        data = validated(ScoreSheetWriteSerializer, request, request.data)
        classroom, subject, term = data["classroom"], data["subject"], data["term"]
        if not can_enter_scores(request.user, classroom, subject, term):
            raise PermissionDenied("You don't teach this subject to this class.")
        lock_term(term)
        if is_published(term):
            raise TermPublished()
        for entry in data["scores"]:
            key = {
                "student": entry["student"],
                "subject": subject,
                "term": term,
                "component": entry["component"],
            }
            if entry["value"] is None:
                Score.objects.filter(**key).delete()
            else:
                Score.objects.update_or_create(
                    **key, defaults={"value": entry["value"], "entered_by": request.user}
                )
        return Response(self.sheet(request.user, classroom, subject, term))

    @staticmethod
    def sheet(user, classroom, subject, term):
        components = list(classroom.school.components.order_by("order"))
        students = class_students(classroom, term.session)
        values = {}
        for score in Score.objects.filter(subject=subject, term=term, student__in=students):
            values[(score.student_id, score.component_id)] = score.value
        rows = []
        for student in students:
            marks = {c.pk: values.get((student.pk, c.pk)) for c in components}
            entered = [v for v in marks.values() if v is not None]
            rows.append(
                {
                    "student": {"id": student.pk, "name": student.display_name},
                    "scores": {str(cid): dec(v) for cid, v in marks.items()},
                    "total": dec(sum(entered)) if entered else None,
                }
            )
        published = is_published(term)
        return {
            "classroom": {"id": classroom.pk, "name": classroom.name},
            "subject": {"id": subject.pk, "name": subject.name},
            "term": {"id": term.pk, "name": term.name, "session": term.session.name},
            "published": published,
            "can_edit": not published and can_enter_scores(user, classroom, subject, term),
            "components": [
                {"id": c.pk, "name": c.name, "max_score": c.max_score} for c in components
            ],
            "rows": rows,
        }


class CommentsView(APIView):
    """PUT {student, term?, form_teacher_comment?, principal_comment?}.

    The form teacher writes theirs, the admin writes the principal's (and may write both).
    Comments lock with the term's results.
    """

    @transaction.atomic
    def put(self, request):
        data = validated(CommentSerializer, request, request.data)
        student, term, user = data["student"], data["term"], request.user
        enrollment = enrollment_for(student, term.session)
        if enrollment is None:
            raise NotFound("This student isn't in a class that session.")
        classroom = enrollment.classroom
        if "form_teacher_comment" in data and not (
            is_admin(user) or is_form_teacher(user, classroom)
        ):
            raise PermissionDenied("Only the form teacher or an admin writes this comment.")
        if "principal_comment" in data and not is_admin(user):
            raise PermissionDenied("Only an admin writes the principal's comment.")
        lock_term(term)
        if is_published(term):
            raise TermPublished()
        result, _ = TermResult.objects.get_or_create(
            student=student, term=term, defaults={"classroom": classroom}
        )
        for field in ("form_teacher_comment", "principal_comment"):
            if field in data:
                setattr(result, field, data[field])
        result.save()
        return Response(
            {
                "student": student.pk,
                "term": term.pk,
                "form_teacher_comment": result.form_teacher_comment,
                "principal_comment": result.principal_comment,
            }
        )


class PublishView(APIView):
    """POST {term?}: compute and store every report card for the term, lock its scores."""

    permission_classes = [IsAdmin]

    @transaction.atomic
    def post(self, request):
        term = validated(TermOnlySerializer, request, request.data)["term"]
        lock_term(term)
        if is_published(term):
            raise InUse("This term is already published.")
        publication = publish_term(term, request.user)
        return Response(
            {
                "term": term.pk,
                "published_at": publication.published_at,
                "report_cards": TermResult.objects.filter(term=term).count(),
            },
            status=201,
        )


class UnpublishView(APIView):
    """POST {term?}: take the term's report cards down for corrections (comments are kept)."""

    permission_classes = [IsAdmin]

    @transaction.atomic
    def post(self, request):
        term = validated(TermOnlySerializer, request, request.data)["term"]
        lock_term(term)
        if not is_published(term):
            raise InUse("This term isn't published.")
        unpublish_term(term)
        return Response({"term": term.pk, "published": False})


class ReportCardView(APIView):
    """GET ?student=&term= (students may omit student; term defaults to the current one).

    Published: the stored report card, for staff who review the class, the student and their
    parents. Not yet published: a live draft, for admins and the form teacher only.
    """

    def get(self, request):
        user = request.user
        data = validated(StudentTermSerializer, request, request.query_params)
        term = data["term"]
        student = data.get("student") or (user if user.role == User.Role.STUDENT else None)
        if student is None:
            raise NotFound("Say which student (?student=<id>).")

        # a published card stands on its own: it stays readable after the student leaves
        # the class, so it is looked up (and authorised) by the class stored on it
        publication = Publication.objects.filter(term=term).first()
        if publication is not None:
            result = (
                TermResult.objects.select_related("student", "classroom__level", "term__session")
                .prefetch_related("subject_results")
                .filter(student=student, term=term)
                .first()
            )
            if result is None or not can_read_published_card(user, student, result.classroom):
                raise NotFound("No report card for this student and term.")
            return Response(report_cards.from_snapshot(result, publication))

        enrollment = enrollment_for(student, term.session)
        if enrollment is None:
            raise NotFound("No report card for this student and term.")
        classroom = enrollment.classroom
        if can_review_class(user, classroom):
            return Response(report_cards.live(student, classroom, term))
        raise NotFound("Results for this term are not published yet.")


class ClassResultsView(APIView):
    """GET ?classroom=&term=: the class broadsheet (every student, every subject) for admins
    and the form teacher. Computed live from the scores until the term is published, then read
    from the stored report cards so it always agrees with them.
    """

    def get(self, request):
        data = validated(ClassTermSerializer, request, request.query_params)
        classroom, term = data["classroom"], data["term"]
        if not can_review_class(request.user, classroom):
            raise PermissionDenied("Only admins and the form teacher see the class results.")
        published = is_published(term)
        rows, stats = (
            self.from_snapshot(classroom, term) if published else self.live(classroom, term)
        )
        subjects = sorted(stats)
        return Response(
            {
                "classroom": {"id": classroom.pk, "name": classroom.name},
                "term": {"id": term.pk, "name": term.name, "session": term.session.name},
                "published": published,
                "subjects": subjects,
                "subject_stats": {name: stats[name] for name in subjects},
                "rows": rows,
            }
        )

    @staticmethod
    def row(student, totals, total, average, gpa, subjects_count, position, out_of):
        return {
            "student": {"id": student.pk, "name": student.display_name},
            "totals": totals,
            "total": dec(total),
            "average": dec(average),
            "gpa": dec(gpa),
            "subjects_count": subjects_count,
            "position": position,
            "out_of": out_of,
        }

    @staticmethod
    def stat(average, highest, lowest):
        return {"average": dec(average), "highest": dec(highest), "lowest": dec(lowest)}

    def live(self, classroom, term):
        computed = compute_class_results(classroom, term)
        rows, stats = [], {}
        for result in computed["students"]:
            summary = result["summary"]
            for line in result["subjects"]:
                stats[line["subject"].name] = self.stat(
                    line["class_average"], line["class_highest"], line["class_lowest"]
                )
            rows.append(
                self.row(
                    result["student"],
                    {line["subject"].name: dec(line["total"]) for line in result["subjects"]},
                    summary["total"],
                    summary["average"],
                    summary["gpa"],
                    summary["subjects_count"],
                    summary["position"],
                    summary["out_of"],
                )
            )
        return rows, stats

    def from_snapshot(self, classroom, term):
        results = (
            TermResult.objects.filter(term=term, classroom=classroom)
            .select_related("student")
            .prefetch_related("subject_results")
            .order_by("student__last_name", "student__first_name", "student__username")
        )
        rows, stats = [], {}
        for result in results:
            lines = result.subject_results.all()
            for line in lines:
                stats[line.subject_name] = self.stat(
                    line.class_average, line.class_highest, line.class_lowest
                )
            rows.append(
                self.row(
                    result.student,
                    {line.subject_name: dec(line.total) for line in lines},
                    result.total,
                    result.average,
                    result.gpa,
                    result.subjects_count,
                    result.position,
                    result.out_of,
                )
            )
        return rows, stats
