from django.conf import settings
from django.core.cache import cache
from django.db import connection as db_connection
from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle
from rest_framework.views import APIView

from api.serializers import (
    ConnectSerializer,
    FileListQuerySerializer,
    JobSubmitSerializer,
    PageQuerySerializer,
    PreviewQuerySerializer,
)
from config import celery_app
from config.container import connection_service, job_service, preview_service
from domain.connections import Connection, S3Credentials
from domain.jobs import Job

# Holds the connection token. HttpOnly keeps it from JavaScript, SameSite=Strict from other sites,
# and using a cookie at all keeps it out of URLs and therefore out of access logs.
CONNECTION_COOKIE = "nl2regex_connection"
_COOKIE_ATTRIBUTES = {"path": "/api", "samesite": "Strict"}


def _check(probe):
    try:
        return bool(probe())
    except Exception:
        return False


@api_view(["GET"])
def health(request):
    """Report whether each backing service is reachable from the web process."""
    checks = {
        "database": _check(lambda: db_connection.ensure_connection() or True),
        "redis": _check(lambda: cache.set("health", 1, 5) or True),
        "worker": _check(lambda: celery_app.control.ping(timeout=2, limit=1)),
    }
    return Response(checks, status=200 if all(checks.values()) else 503)


class ConnectRateThrottle(AnonRateThrottle):
    """Without a limit, the connect endpoint could be used to test stolen AWS keys in bulk."""

    scope = "connect"


class ConnectionView(APIView):
    def get_throttles(self):
        # Only connecting is limited. Reading the connection happens on every page load.
        return [ConnectRateThrottle()] if self.request.method == "POST" else []

    def post(self, request):
        serializer = ConnectSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        token, connection = connection_service().connect(
            S3Credentials(data["access_key_id"], data["secret_access_key"]),
            data["bucket"],
            previous_token=request.COOKIES.get(CONNECTION_COOKIE),
        )
        response = Response(_describe(connection), status=201)
        # No max-age: the vault is the only expiry clock, and the cookie dies with the browser.
        response.set_cookie(
            CONNECTION_COOKIE,
            token,
            httponly=True,
            secure=not settings.DEBUG,
            **_COOKIE_ATTRIBUTES,
        )
        return response

    def get(self, request):
        connection = connection_service().get(request.COOKIES.get(CONNECTION_COOKIE))
        return Response(_describe(connection))

    def delete(self, request):
        token = request.COOKIES.get(CONNECTION_COOKIE)
        # Disconnecting forgets everything: the jobs and their output first, then the keys.
        job_service().forget_jobs(token)
        connection_service().disconnect(token)
        response = Response(status=204)
        response.delete_cookie(CONNECTION_COOKIE, **_COOKIE_ATTRIBUTES)
        return response


class FileListView(APIView):
    def get(self, request):
        query = FileListQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)

        listing = connection_service().list_files(
            request.COOKIES.get(CONNECTION_COOKIE),
            query.validated_data["prefix"],
            query.validated_data["page_token"],
        )
        return Response(
            {
                "prefix": query.validated_data["prefix"],
                "folders": listing.folders,
                "files": [
                    {
                        "key": file.key,
                        "size": file.size,
                        "last_modified": file.last_modified,
                        "format": file.format.value if file.format else None,
                    }
                    for file in listing.files
                ],
                "next_token": listing.next_token,
            }
        )


class FilePreviewView(APIView):
    def get(self, request):
        """Poll this URL. The first call starts a background read; later calls report on it."""
        query = PreviewQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        return Response(
            preview_service().get(
                request.COOKIES.get(CONNECTION_COOKIE), query.validated_data["key"]
            )
        )


class JobSubmitThrottle(AnonRateThrottle):
    scope = "jobs"


class JobListView(APIView):
    def get_throttles(self):
        return [JobSubmitThrottle()] if self.request.method == "POST" else []

    def get(self, request):
        jobs = job_service().recent(request.COOKIES.get(CONNECTION_COOKIE))
        return Response({"jobs": [_job_json(job) for job in jobs]})

    def post(self, request):
        serializer = JobSubmitSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        job = job_service().submit(
            request.COOKIES.get(CONNECTION_COOKIE), **serializer.validated_data
        )
        # 202 Accepted: the work has been queued, not done.
        return Response(_job_json(job), status=202)


class JobDetailView(APIView):
    def get(self, request, job_id):
        return Response(
            _job_json(job_service().get(request.COOKIES.get(CONNECTION_COOKIE), str(job_id)))
        )


class JobCancelView(APIView):
    def post(self, request, job_id):
        job = job_service().cancel(request.COOKIES.get(CONNECTION_COOKIE), str(job_id))
        return Response(_job_json(job))


class JobRowsView(APIView):
    def get(self, request, job_id):
        query = PageQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        page = job_service().read_page(
            request.COOKIES.get(CONNECTION_COOKIE), str(job_id), **query.validated_data
        )
        return Response(
            {
                "columns": page.columns,
                "rows": page.rows,
                "page": page.page,
                "page_size": page.page_size,
                "total_rows": page.total_rows,
            }
        )


def _job_json(job: Job) -> dict:
    # Named fields only, as with connections. The connection ID stays on the server.
    return {
        "id": job.id,
        "status": job.status.value,
        "progress": job.progress,
        "stage": job.stage,
        "cancel_requested": job.cancel_requested,
        "file_key": job.file_key,
        "file_format": job.file_format.value,
        "pattern": job.pattern,
        "replacement": job.replacement,
        "columns": job.columns,
        "error": (
            {"code": job.error_code, "message": job.error_message} if job.error_code else None
        ),
        "rows_total": job.rows_total,
        "rows_changed": job.rows_changed,
        "attempts": job.attempts,
        "created_at": job.created_at,
        "started_at": job.started_at,
        "finished_at": job.finished_at,
    }


def _describe(connection: Connection) -> dict:
    # Named fields only. dataclasses.asdict() would include the credentials.
    return {"bucket": connection.bucket, "region": connection.region}
