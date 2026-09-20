"""Asks Claude to write the pattern. The request is the only thing it is ever sent."""

import pydantic

from domain.errors import LLMNotConfigured, PatternNotUnderstood
from domain.patterns import PatternSuggestion, Rejection
from infrastructure import claude_api

# Part of the cache key. Raise it whenever the instructions below change what Claude would answer.
INSTRUCTIONS_VERSION = 2

INSTRUCTIONS = """You turn a plain-English request into one regular expression for a find-and-replace tool that cleans tabular data.

The request
- It may be a sentence ("find email addresses and replace them with X") or only a noun phrase ("phone numbers", "prices in US dollars"). Both ask you to find that thing.
- When it is general, cover the common ways the thing is written. "Phone numbers" means with or without parentheses, spaces, dots, dashes and a country code. When it gives an example or a format, match that format.

How the pattern is used
- It is applied to each cell of the chosen columns, as text. Every match in a cell is replaced, so do not anchor with ^ or $ unless the request is about the start, the end or the whole of a cell.
- It must behave the same in Python's re module and in Java's java.util.regex. Use only syntax both accept: no named groups, no conditionals, no possessive quantifiers, no atomic groups, no variable-length lookbehind, and no inline flags other than a leading (?i).
- \\w, \\d, \\s and \\b are Unicode-aware, and . does not match a line break.
- It must run in linear time. Never nest quantifiers, as in (a+)+ or (.*a){5}. Never repeat a group whose alternatives can match the same text, as in (a|aa)+. Bound a repetition where the thing described has a natural length.
- Match the whole of the thing described and nothing around it, so that replacing it leaves the rest of the cell intact.
- Put \\b only where the neighbouring character of the match is a letter, a digit or an underscore. Next to punctuation such as ( $ # or + it does the opposite of what is wanted. To stop a match from starting or ending inside a longer run, use a lookaround such as (?<![\\d.]) and (?![\\d.]).
- Use (?i) when the request is about words or placeholders whose capitalisation can vary.

What to return
- understood: false only if the request is not about finding something in text, such as a question or a command unrelated to data. Then give a short reason and leave pattern empty.
- pattern: the regular expression alone, not wrapped in slashes or quotes.
- explanation: one plain sentence saying what it matches, with a short example.
- replacement: the replacement text if, and only if, the request states one ("replace them with 'REDACTED'" gives REDACTED; "remove", "delete" or "get rid of" gives an empty string). Otherwise null.
- columns: the column names the request mentions, exactly as written. Otherwise an empty list.
- should_match: 3 to 5 short strings that each contain at least one match.
- should_not_match: 3 to 5 short strings in which the pattern must find nothing at all, not even inside a longer token. Keep them plain. Do not use a borderline case you are unsure of.
Your pattern will be run against both lists, and an answer whose pattern disagrees with its own examples is refused. Check each one before you answer."""  # noqa: E501


class _Answer(pydantic.BaseModel):
    """The shape Claude must answer in."""

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
        self._client = claude_api.client(api_key, timeout)
        self._model = model

    def write(self, request: str, rejected: Rejection | None = None) -> PatternSuggestion:
        content = request
        task = "pattern"
        if rejected is not None:
            task = "pattern-retry"
            content += (
                f"\n\nAn earlier answer was refused. Its pattern was {rejected.pattern!r}. "
                f"{rejected.reason} Either the pattern or an example was wrong. Answer again, "
                "with a pattern that agrees with every one of its examples."
            )
        answer = claude_api.ask(self._client, self._model, task, INSTRUCTIONS, content, _Answer)
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
