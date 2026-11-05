"""GET /healthz/: for load balancers and container health checks. No login, no rate limit,
no HTTPS redirect; 200 when the app can reach its database, 503 when it can't.

Redis (when used) is reported but doesn't fail the check: every app server shares it, so an
outage would take them all out of rotation at once. Without it rate limits pause and background
jobs can't be queued; ``"status": "degraded"`` says so, for monitoring to alert on."""

import logging

from django.conf import settings
from django.db import connection
from django.http import JsonResponse

logger = logging.getLogger(__name__)


def healthz(request):
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
    except Exception:  # any database failure means "not healthy"
        logger.exception("health check: database unreachable")
        return JsonResponse({"status": "error", "database": "unreachable"}, status=503)
    if settings.JOBS_ASYNC:
        import django_rq

        try:
            django_rq.get_connection("default").ping()
        except Exception:
            logger.exception("health check: redis unreachable")
            return JsonResponse({"status": "degraded", "redis": "unreachable"})
    return JsonResponse({"status": "ok"})
