"""Use-case: turn a plain-English request into a pattern that is safe to run on a large file."""

import logging
import re

from domain.errors import DomainError, PatternNotVerified
from domain.patterns import PatternSuggestion, Rejection
from domain.ports import PatternCache, PatternProbe, PatternWriter

logger = logging.getLogger(__name__)

# Syntax Python accepts and Java's regex engine, which runs the job, does not.
_PYTHON_ONLY = {
    "(?P<": "a named group written (?P<name>...)",
    "(?P=": "a named backreference written (?P=name)",
    "(?(": "a conditional group",
    "\\N{": "a named Unicode escape",
    "(?a": "the ASCII flag",
    "(?L": "the locale flag",
}


def normalise(request: str) -> str:
    """Requests that differ only in case, spacing or a final full stop are the same request."""
    return " ".join(request.lower().split()).rstrip(".!? ")


class PatternService:
    def __init__(
        self, writer: PatternWriter, cache: PatternCache, probe: PatternProbe, max_attempts: int = 3
    ):
        self._writer = writer
        self._cache = cache
        self._probe = probe
        self._max_attempts = max_attempts

    def suggest(self, request: str) -> tuple[PatternSuggestion, bool]:
        """The pattern for a request, and whether it came from the cache.

        The model's answer is not trusted. It has to compile, avoid Python-only syntax, pass the
        examples the model wrote for it, and survive the timed dry run. Each failure goes back to
        the model once as the reason to try again. Only a pattern that passed is cached.
        """
        key = normalise(request)
        cached = self._cache.get(key)
        if cached is not None:
            return cached, True

        rejected: Rejection | None = None
        for _ in range(self._max_attempts):
            suggestion = self._writer.write(request, rejected)
            try:
                self._verify(suggestion)
            except _Refused as refusal:
                logger.info("A written pattern was refused: %s", refusal.reason[:60])
                rejected = Rejection(suggestion.pattern, refusal.reason)
                continue
            self._cache.put(key, suggestion)
            return suggestion, False
        raise PatternNotVerified(rejected.reason)

    @property
    def can_write(self) -> bool:
        """False when no language model is configured, so only typed patterns can be run."""
        return self._writer.is_configured

    def check(self, pattern: str) -> None:
        """For a pattern the user typed. It compiled when it was submitted; is it safe to run?"""
        self._probe.check(pattern)

    def _verify(self, suggestion: PatternSuggestion) -> None:
        if not suggestion.pattern:
            raise _Refused("The pattern is empty.")
        try:
            compiled = re.compile(suggestion.pattern)
        except re.error as error:
            raise _Refused(f"It is not a valid regular expression: {error}.") from error
        for syntax, name in _PYTHON_ONLY.items():
            if syntax in suggestion.pattern:
                raise _Refused(f"It uses {name}, which Java's regex engine does not accept.")

        # The model's own test cases. What matched is quoted, because the usual cause is a valid
        # match sitting inside a longer string that was meant to be left alone.
        problems = [
            f"it finds nothing in {text!r}, which it was meant to match"
            for text in suggestion.should_match
            if not compiled.search(text)
        ] + [
            f"it matches {found.group()!r} in {text!r}, which it was meant to leave alone"
            for text in suggestion.should_not_match
            if (found := compiled.search(text))
        ]
        if problems:
            raise _Refused(
                f"The pattern disagrees with its own examples: {'; '.join(problems[:3])}."
            )

        try:
            self._probe.check(suggestion.pattern)
        except DomainError as unsafe:
            raise _Refused(unsafe.message) from unsafe


class _Refused(Exception):
    """A written pattern failed a check. The reason is a sentence for the model and the user."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason
