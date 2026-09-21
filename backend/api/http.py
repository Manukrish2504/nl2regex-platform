"""What the views and their throttles both need: how a request carries its connection, and the
limits on how often one may arrive. Calls to AWS are limited per IP; calls that cost money are
metered on their own, because those are charged to this server rather than to the caller."""

import hashlib

from rest_framework.throttling import AnonRateThrottle, SimpleRateThrottle

from domain.jobs import needs_model

# Holds the connection token. HttpOnly keeps it from JavaScript, SameSite=Strict from other sites,
# and using a cookie at all keeps it out of URLs and therefore out of access logs.
CONNECTION_COOKIE = "nl2regex_connection"
COOKIE_ATTRIBUTES = {"path": "/api", "samesite": "Strict"}

# Shown instead of DRF's wording when one of the two model limits is the one that tripped, so the
# answer names the way through: the same job with a typed pattern costs nothing and still runs.
CAPPED = (
    "This server has reached its limit for requests that use the language model. "
    "Switch to Regex mode to keep working, or try again later."
)


class ConnectRateThrottle(AnonRateThrottle):
    """Without a limit, the connect endpoint could be used to test stolen AWS keys in bulk."""

    scope = "connect"


class JobSubmitThrottle(AnonRateThrottle):
    scope = "jobs"


class ModelThrottle(SimpleRateThrottle):
    """Counts only the submissions that would call the model; the rest are not its business.

    A denial is recorded on the request so the view can answer with CAPPED rather than DRF's
    generic wording, which would send someone away from a feature that still works.
    """

    def allow_request(self, request, view):
        data = request.data if isinstance(request.data, dict) else {}
        if not needs_model(data.get("kind", "replace"), data.get("prompt")):
            return True
        allowed = super().allow_request(request, view)
        if not allowed:
            request.model_capped = True
        return allowed


class ModelPerConnectionThrottle(ModelThrottle):
    """One connection's share. Bypassable by connecting again, which is what the server-wide
    limit below is for; this one keeps a single honest user from spending the whole budget."""

    scope = "llm_connection"

    def get_cache_key(self, request, view):
        token = request.COOKIES.get(CONNECTION_COOKIE)
        if not token:
            return None  # no connection: the request is about to be refused anyway
        # The same SHA-256 the vault keys connections by. The token itself is never written down.
        return self.cache_format % {
            "scope": self.scope,
            "ident": hashlib.sha256(token.encode()).hexdigest(),
        }


class ModelPerServerThrottle(ModelThrottle):
    """Everyone together. This is the one that bounds the bill."""

    scope = "llm_server"

    def get_cache_key(self, request, view):
        return self.cache_format % {"scope": self.scope, "ident": "server"}
