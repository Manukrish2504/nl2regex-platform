import hashlib

from django.core.cache import cache

from domain.patterns import PatternSuggestion


class CacheStore:
    """Answers from a language model, kept in the Django cache (Redis).

    The namespace names the model and the version of the instructions it was given. A change to
    either could change the answer, so it starts a fresh set of keys and never serves an old one.
    """

    def __init__(self, kind: str, namespace: str, ttl: int):
        self._prefix = f"{kind}:{namespace}"
        self._ttl = ttl

    def get(self, key: str) -> dict | None:
        return cache.get(f"{self._prefix}:{key}")

    def put(self, key: str, value: dict) -> None:
        cache.set(f"{self._prefix}:{key}", value, self._ttl)


class CachePatternStore(CacheStore):
    """The same, keyed by the request a pattern answers, holding the suggestion itself."""

    def get(self, request: str) -> PatternSuggestion | None:
        entry = super().get(_digest(request))
        return PatternSuggestion(**entry) if entry else None

    def put(self, request: str, suggestion: PatternSuggestion) -> None:
        super().put(_digest(request), vars(suggestion))


def _digest(request: str) -> str:
    return hashlib.sha256(request.encode()).hexdigest()
