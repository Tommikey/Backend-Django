"""Give every existing session its own copy of the school's score split, and point that
session's scores at the copy. The rows without a session stay as the school's default."""

from django.db import migrations


def split_by_session(apps, schema_editor):
    Component = apps.get_model("schools", "AssessmentComponent")
    Session = apps.get_model("academics", "AcademicSession")
    Score = apps.get_model("results", "Score")
    school_ids = Component.objects.filter(session__isnull=True).values_list("school_id", flat=True)
    for school_id in set(school_ids):
        defaults = list(
            Component.objects.filter(school_id=school_id, session__isnull=True).order_by("order")
        )
        for session in Session.objects.filter(school_id=school_id):
            for default in defaults:
                copy = Component.objects.create(
                    school_id=school_id,
                    session=session,
                    name=default.name,
                    max_score=default.max_score,
                    order=default.order,
                )
                Score.objects.filter(component=default, term__session=session).update(
                    component=copy
                )


def merge_back(apps, schema_editor):
    """Undo: point scores at the default component of the same name, drop per-session rows."""
    Component = apps.get_model("schools", "AssessmentComponent")
    Score = apps.get_model("results", "Score")
    for copy in Component.objects.filter(session__isnull=False):
        default, _ = Component.objects.get_or_create(
            school_id=copy.school_id,
            session=None,
            name=copy.name,
            defaults={"max_score": copy.max_score, "order": copy.order},
        )
        Score.objects.filter(component=copy).update(component=default)
        copy.delete()


class Migration(migrations.Migration):
    dependencies = [
        ("schools", "0002_score_split_per_session"),
        ("academics", "0004_enrollment_outcome"),
        ("results", "0002_termresult_attendance"),
    ]

    operations = [migrations.RunPython(split_by_session, merge_back)]
