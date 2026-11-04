"""Per-row counts and averages as subquery annotations, so a list of classes costs one query
however many classes there are."""

from django.db.models import Avg, Count, F, FloatField, IntegerField, OuterRef, Subquery
from django.db.models.functions import Coalesce


def count_per(queryset, link):
    """Number of rows of ``queryset`` whose ``link`` field points at the outer row."""
    counts = (
        queryset.filter(**{link: OuterRef("pk")})
        .order_by()
        .values(link)
        .annotate(n=Count("pk"))
        .values("n")[:1]
    )
    return Coalesce(Subquery(counts, output_field=IntegerField()), 0)


def score_pct_per(submissions, link):
    """Mean score, as a percentage of each assessment's max points, of the scored
    ``submissions`` whose ``link`` field points at the outer row (None if none are scored)."""
    averages = (
        submissions.filter(
            **{link: OuterRef("pk")}, score__isnull=False, assessment__max_points__gt=0
        )
        .order_by()
        .values(link)
        .annotate(
            pct=Avg(F("score") * 100.0 / F("assessment__max_points"), output_field=FloatField())
        )
        .values("pct")[:1]
    )
    return Subquery(averages, output_field=FloatField())


def one_decimal(value):
    return None if value is None else round(value, 1)
