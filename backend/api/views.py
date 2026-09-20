from django.core.cache import cache
from django.db import connection
from rest_framework.decorators import api_view
from rest_framework.response import Response

from config import celery_app


def _check(probe):
    try:
        return bool(probe())
    except Exception:
        return False


@api_view(["GET"])
def health(request):
    """Report whether each backing service is reachable from the web process."""
    checks = {
        "database": _check(lambda: connection.ensure_connection() or True),
        "redis": _check(lambda: cache.set("health", 1, 5) or True),
        "worker": _check(lambda: celery_app.control.ping(timeout=2, limit=1)),
    }
    return Response(checks, status=200 if all(checks.values()) else 503)
