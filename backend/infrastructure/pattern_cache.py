import hashlib
from dataclasses import asdict

from django.core.cache import cache

from domain.patterns import PatternSuggestion


class CachePatternStore:
    """Verified patterns live in the Django cache (Redis), keyed by the request they answer.

    The namespace names the model and the version of the instructions it was given. A change to
    either could change the answer, so it starts a fresh set of keys and never serves an old one.
    """

    def __init__(self, namespace: str, ttl: int):
        self._namespace = namespace
        self._ttl = ttl

    def get(self, request: str) -> PatternSuggestion | None:
        entry = cache.get(self._key(request))
        return PatternSuggestion(**entry) if entry else None

    def put(self, request: str, suggestion: PatternSuggestion) -> None:
        cache.set(self._key(request), asdict(suggestion), self._ttl)

    def _key(self, request: str) -> str:
        return f"pattern:{self._namespace}:{hashlib.sha256(request.encode()).hexdigest()}"
