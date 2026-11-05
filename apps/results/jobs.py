"""Background tasks for results (run by apps/jobs/queue.py)."""

from apps.academics.models import Term
from apps.jobs.queue import JobRefused

from .models import TermResult
from .services import is_published, lock_term, publish_term


def publish_results(job):
    term = Term.objects.get(pk=job.params["term"], session__school=job.school)
    lock_term(term)
    if is_published(term):
        raise JobRefused("This term is already published.")
    publication = publish_term(term, job.created_by)
    return {
        "term": term.pk,
        "published_at": publication.published_at.isoformat(),
        "report_cards": TermResult.objects.filter(term=term).count(),
    }
