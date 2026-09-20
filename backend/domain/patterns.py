"""A pattern written from a plain-English request. Standard library only."""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class PatternSuggestion:
    """What the language model returns for one request.

    `replacement` and `columns` are filled only when the request itself states them, as in
    "replace emails in the Email column with REDACTED". The examples are the model's own test
    cases; a pattern is not used until it passes them.
    """

    pattern: str
    explanation: str
    replacement: str | None = None
    columns: list[str] = field(default_factory=list)
    should_match: list[str] = field(default_factory=list)
    should_not_match: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Rejection:
    """Why a pattern was refused, sent back to the model so that its next attempt differs."""

    pattern: str
    reason: str
