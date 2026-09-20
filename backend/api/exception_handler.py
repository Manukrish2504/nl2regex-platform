import logging

from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler

from domain import errors

logger = logging.getLogger(__name__)

_STATUS_BY_DOMAIN_ERROR = {
    errors.InvalidCredentials: 400,
    errors.InvalidPageToken: 400,
    errors.ConnectionNotFound: 401,
    errors.BucketAccessDenied: 403,
    errors.BucketNotFound: 404,
    errors.StorageUnreachable: 502,
    errors.StorageError: 502,
}


def handle(exc, context):
    """Every API failure leaves in one shape: {"error": {"code", "message"}}."""
    if isinstance(exc, errors.DomainError):
        return _envelope(exc.code, exc.message, _STATUS_BY_DOMAIN_ERROR.get(type(exc), 500))

    response = drf_exception_handler(exc, context)
    if response is None:
        # Answering here keeps Django's DEBUG error page, which prints local variables such as a
        # submitted secret key, from ever rendering for an API request.
        logger.exception("Unhandled error in %s", type(context["view"]).__name__)
        return _envelope("internal_error", "Something went wrong on our side.", 500)

    if isinstance(exc, ValidationError):
        error = {
            "code": "validation_error",
            "message": "Some fields are invalid.",
            "fields": response.data,
        }
    else:
        error = {
            "code": getattr(exc, "default_code", "error"),
            "message": str(response.data.get("detail", "")),
        }
    response.data = {"error": error}  # keeps DRF's headers, e.g. Retry-After on a 429
    return response


def _envelope(code: str, message: str, status: int) -> Response:
    return Response({"error": {"code": code, "message": message}}, status=status)
