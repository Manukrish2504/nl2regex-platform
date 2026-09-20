from django.conf import settings
from django.core.cache import cache
from django.db import connection as db_connection
from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle
from rest_framework.views import APIView

from api.serializers import ConnectSerializer, FileListQuerySerializer
from config import celery_app
from config.container import connection_service
from domain.connections import Connection, S3Credentials

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
        connection_service().disconnect(request.COOKIES.get(CONNECTION_COOKIE))
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


def _describe(connection: Connection) -> dict:
    # Named fields only. dataclasses.asdict() would include the credentials.
    return {"bucket": connection.bucket, "region": connection.region}
