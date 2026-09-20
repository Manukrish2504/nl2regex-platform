import hashlib

from django.core.cache import cache

PENDING_SECONDS = 120  # if the worker never answers, the next request may try again
FAILED_SECONDS = 30  # a failure is remembered briefly, so a retry is possible


class CachePreviewStore:
    """Previews live in the Django cache (Redis), keyed by connection and file."""

    def __init__(self, ttl: int):
        self._ttl = ttl

    def get(self, connection_id: str, file_key: str) -> dict | None:
        return cache.get(_key(connection_id, file_key))

    def mark_pending(self, connection_id: str, file_key: str) -> bool:
        # cache.add only writes when the key is absent, which makes the claim atomic.
        return cache.add(_key(connection_id, file_key), {"status": "pending"}, PENDING_SECONDS)

    def put(self, connection_id: str, file_key: str, entry: dict) -> None:
        ttl = FAILED_SECONDS if entry["status"] == "failed" else self._ttl
        cache.set(_key(connection_id, file_key), entry, ttl)


def _key(connection_id: str, file_key: str) -> str:
    return f"preview:{connection_id}:{hashlib.sha256(file_key.encode()).hexdigest()}"
