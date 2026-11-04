"""GET /healthz/: for load balancers and container health checks. No login, no rate limit,
no HTTPS redirect; 200 when the app can reach its database, 503 when it can't."""

import logging

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
    return JsonResponse({"status": "ok"})
