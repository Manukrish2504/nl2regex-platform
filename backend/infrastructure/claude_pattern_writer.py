"""Asks Claude to write the pattern. The request is the only thing it is ever sent."""

import logging
import time

import anthropic
import pydantic

from domain.errors import (
    LLMNotConfigured,
    LLMRejectedRequest,
    LLMUnavailable,
    PatternNotUnderstood,
)
from domain.patterns import PatternSuggestion, Rejection

logger = logging.getLogger(__name__)

# Part of the cache key. Raise it whenever the instructions below change what Claude would answer.
INSTRUCTIONS_VERSION = 1

INSTRUCTIONS = """You turn a plain-English request into one regular expression for a find-and-replace tool that cleans tabular data.

How the pattern is used
- It is applied to each cell of the chosen columns, as text. Every match in a cell is replaced, so do not anchor with ^ or $ unless the request is about the start, the end or the whole of a cell.
- It must behave the same in Python's re module and in Java's java.util.regex. Use only syntax both accept: no named groups, no conditionals, no possessive quantifiers, no atomic groups, no variable-length lookbehind, and no inline flags other than a leading (?i).
- \\w, \\d, \\s and \\b are Unicode-aware, and . does not match a line break.
- It must run in linear time. Never nest quantifiers, as in (a+)+ or (.*a){5}. Never repeat a group whose alternatives can match the same text, as in (a|aa)+. Bound a repetition where the thing described has a natural length.
- Match the whole of the thing described and nothing around it, so that replacing it leaves the rest of the cell intact. Use \\b at the edges of words and numbers.

What to return
- understood: false only if the request does not describe something to find in text. Then give a short reason and leave pattern empty.
- pattern: the regular expression alone, not wrapped in slashes or quotes.
- explanation: one plain sentence saying what it matches, with a short example.
- replacement: the replacement text if, and only if, the request states one ("replace them with 'REDACTED'" gives REDACTED; "remove" or "delete" gives an empty string). Otherwise null.
- columns: the column names the request mentions, exactly as written. Otherwise an empty list.
- should_match: 3 to 5 short strings that each contain at least one match.
- should_not_match: 3 to 5 short strings that look similar but must produce no match. Your pattern will be run against both lists, so make sure it agrees with them."""  # noqa: E501


class _Answer(pydantic.BaseModel):
    """The shape Claude must answer in. Decoding is constrained to it, so a regex arrives with
    its backslashes intact, which asking for "JSON with a regex in it" does not guarantee."""

    understood: bool
    reason: str
    pattern: str
    explanation: str
    replacement: str | None
    columns: list[str]
    should_match: list[str]
    should_not_match: list[str]


class ClaudePatternWriter:
    is_configured = True

    def __init__(self, api_key: str, model: str, timeout: float):
        self._client = anthropic.Anthropic(api_key=api_key, timeout=timeout, max_retries=2)
        self._model = model

    def write(self, request: str, rejected: Rejection | None = None) -> PatternSuggestion:
        content = request
        if rejected is not None:
            content += (
                f"\n\nAn earlier answer, {rejected.pattern!r}, was refused. {rejected.reason} "
                "Write a different pattern that does not have this problem."
            )
        started = time.monotonic()
        try:
            message = self._client.messages.parse(
                model=self._model,
                max_tokens=2048,
                system=INSTRUCTIONS,
                messages=[{"role": "user", "content": content}],
                output_format=_Answer,
                # The task needs no deliberation, and thinking triples the wait.
                thinking={"type": "disabled"},
            )
        except anthropic.APIStatusError as error:
            if error.status_code == 429 or error.status_code >= 500:
                raise LLMUnavailable() from error
            # A bad key, no credit, an unknown model: nothing the user can fix, so it is logged
            # for the operator. The status and type only: never the request, never the key.
            logger.error("Claude refused a request: %s %s", error.status_code, type(error).__name__)
            raise LLMRejectedRequest() from error
        except anthropic.APIConnectionError as error:  # includes timeouts
            raise LLMUnavailable() from error

        logger.info(
            "Claude wrote a pattern: model=%s seconds=%.1f tokens_in=%s tokens_out=%s retry=%s",
            self._model,
            time.monotonic() - started,
            message.usage.input_tokens,
            message.usage.output_tokens,
            rejected is not None,
        )
        answer = message.parsed_output
        if answer is None:  # it stopped without a complete answer, which is a refusal in practice
            raise PatternNotUnderstood("the language model declined to answer.")
        if not answer.understood:
            raise PatternNotUnderstood(answer.reason or "it does not describe something to find.")
        return PatternSuggestion(
            pattern=answer.pattern,
            explanation=answer.explanation,
            replacement=answer.replacement,
            columns=answer.columns,
            should_match=answer.should_match,
            should_not_match=answer.should_not_match,
        )


class UnconfiguredPatternWriter:
    """Wired in when the server has no API key. Typed patterns still work."""

    is_configured = False

    def write(self, request: str, rejected: Rejection | None = None) -> PatternSuggestion:
        raise LLMNotConfigured()
