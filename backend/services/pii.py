"""Use-case: find the personal data in a file and plan how to mask it.

The language model classifies; it does not see values and it does not write the patterns. It is
shown each column's name and the shapes of a few values, and it answers with kinds of data. The
patterns for those kinds are ours, tested and run through the same safety probe as any other.
"""

import hashlib
import json
import logging
import re
from collections import Counter
from dataclasses import asdict

from domain.advice import ColumnProfile, Finding
from domain.errors import NothingToChange
from domain.operations import MaskCells, Operation, Replace
from domain.patterns import PatternSuggestion
from domain.ports import AdviceCache, PiiClassifier
from domain.tables import Row, column_indexes
from services.patterns import PatternService, Refused

logger = logging.getLogger(__name__)

SAMPLE_ROWS = 500
SHAPES_PER_COLUMN = 5
TOKEN_SHAPES_PER_COLUMN = 8
_SHAPE_LENGTH = 80

# Kinds that a pattern can find, also inside free text. Each pattern is linear-time, matches the
# whole thing and nothing around it, and is valid in both Python and Java.
PATTERNS: dict[str, tuple[str, str]] = {
    "email": ("[EMAIL]", r"[\w.%+-]+@(?:[\w-]+\.)+[A-Za-z]{2,24}"),
    "phone": (
        "[PHONE]",
        r"(?<![\w+])(?:\+\d{1,3}[\s.-]?)?(?:\(\d{2,4}\)[\s.-]?|\d{2,4}[\s.-])\d{3,4}[\s.-]\d{3,4}"
        r"(?:[\s.-]\d{2,4})?(?!\w)|(?<!\d)\d{10}(?!\d)",
    ),
    "ssn": ("[SSN]", r"(?<!\d)\d{3}-\d{2}-\d{4}(?!\d)"),
    "card": ("[CARD]", r"(?<!\d)\d{4}[ -]?\d{4}[ -]?\d{4}[ -]?\d{1,7}(?!\d)"),
    "ip": ("[IP]", r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])"),
    "url": ("[URL]", r"https?://[^\s<>\"']+"),
}
# Kinds that are sensitive as a whole cell, which no pattern can recognise.
WHOLE_CELL = {
    "name": "[NAME]",
    "address": "[ADDRESS]",
    "date_of_birth": "[DOB]",
    "identifier": "[ID]",
}
OTHER_PLACEHOLDER = "[REDACTED]"
_RUNS = re.compile(r"([aA9])\1+")


def shape_of(value: str) -> str:
    """The value with every letter and digit replaced: "John.Doe@x.com" is "Aaaa.Aaa@a.aaa".

    Punctuation, spacing and length stay, and they are what makes an e-mail, a phone number or a
    date recognisable. No character of the original that could identify anyone survives.
    """
    shape = "".join(
        "9" if c.isdigit() else ("A" if c.isupper() else "a") if c.isalpha() else c
        for c in value[:_SHAPE_LENGTH]
    )
    return shape + ("..." if len(value) > _SHAPE_LENGTH else "")


def profile(columns: list[str], rows: list[Row], wanted: list[str]) -> list[ColumnProfile]:
    profiles = []
    for index in column_indexes(columns, wanted):
        cells = [row[index] for row in rows]
        filled = [cell for cell in cells if cell]
        # A plain word says nothing. A token with a digit or a symbol in it may be an address,
        # a number or a link, wherever in the sentence it sits.
        tokens = [
            token
            for cell in filled
            for token in cell.split()
            if not token.strip(".,;:!?()\"'").isalpha()
        ]
        profiles.append(
            ColumnProfile(
                column=columns[index],
                blank_share=round(1 - len(filled) / len(cells), 2) if cells else 1.0,
                shapes=_common_shapes(filled, SHAPES_PER_COLUMN),
                token_shapes=_common_shapes(tokens, TOKEN_SHAPES_PER_COLUMN),
            )
        )
    return profiles


def _common_shapes(values: list[str], limit: int) -> list[str]:
    """One shape for each of the most common KINDS of value.

    "aaaa99@aaaa.aaa" and "aaaaaaa9@aa.aa" are the same kind of thing at different lengths.
    Counted separately, a column's e-mail addresses alone would fill every place and hide the
    phone numbers beside them. So shapes are grouped by their outline, with runs collapsed, and
    each of the most common groups is shown by its most common member.
    """
    groups: dict[str, Counter[str]] = {}
    for value in values:
        shape = shape_of(value)
        groups.setdefault(_RUNS.sub(r"\1", shape), Counter())[shape] += 1
    ranked = sorted(groups.values(), key=lambda group: -group.total())
    return [group.most_common(1)[0][0] for group in ranked[:limit]]


class PiiService:
    def __init__(self, classifier: PiiClassifier, cache: AdviceCache, patterns: PatternService):
        self._classifier = classifier
        self._cache = cache
        self._patterns = patterns

    def plan(
        self, columns: list[str], rows: list[Row], wanted: list[str]
    ) -> tuple[list[Operation], dict]:
        """The operations that mask what was found, and a report of what that was."""
        profiles = profile(columns, rows, wanted)
        findings, from_cache = self._findings(profiles)

        known = {item.column for item in profiles}
        by_kind: dict[str, list[str]] = {}
        custom: list[Finding] = []
        kept, skipped = [], []
        for finding in findings:
            if finding.column not in known:
                skipped.append(_row(finding, "it names a column that was not in the request"))
            elif finding.kind in PATTERNS or finding.kind in WHOLE_CELL:
                if finding.column not in by_kind.setdefault(finding.kind, []):
                    by_kind[finding.kind].append(finding.column)
                    kept.append(finding)
            elif finding.pattern and (problem := self._refusal(finding)) is None:
                custom.append(finding)
                kept.append(finding)
            else:
                skipped.append(_row(finding, problem if finding.pattern else "it gave no pattern"))

        # Matches inside cells first, whole cells last: masking a cell leaves nothing to match.
        operations: list[Operation] = []
        described = []

        def add(operation: Replace | MaskCells, kind: str) -> None:
            operations.append(operation)
            described.append(
                {"kind": kind, "placeholder": operation.replacement, "columns": operation.columns}
            )

        for kind, (placeholder, pattern) in PATTERNS.items():
            if kind in by_kind:
                add(Replace(pattern, placeholder, by_kind[kind]), kind)
        for finding in custom:
            add(Replace(finding.pattern, OTHER_PLACEHOLDER, [finding.column]), finding.kind)
        for kind, placeholder in WHOLE_CELL.items():
            if kind in by_kind:
                add(MaskCells(placeholder, by_kind[kind]), kind)

        if not operations:
            raise NothingToChange(
                "No personal data was found in the chosen columns, so nothing was changed."
            )
        report = {
            "findings": [_row(finding) for finding in kept],
            "skipped": skipped,
            "operations": described,
            "from_cache": from_cache,
        }
        return operations, report

    def _findings(self, profiles: list[ColumnProfile]) -> tuple[list[Finding], bool]:
        sent = [asdict(item) for item in profiles]
        key = "pii:" + hashlib.sha256(json.dumps(sent, sort_keys=True).encode()).hexdigest()
        cached = self._cache.get(key)
        if cached is not None:
            return [Finding(**item) for item in cached["findings"]], True
        findings = self._classifier.classify(profiles)
        self._cache.put(key, {"findings": [asdict(finding) for finding in findings]})
        return findings, False

    def _refusal(self, finding: Finding) -> str | None:
        """A pattern the model wrote goes through the same checks as any pattern it writes."""
        suggestion = PatternSuggestion(
            pattern=finding.pattern,
            explanation=finding.reason,
            should_match=finding.should_match,
            should_not_match=finding.should_not_match,
        )
        try:
            self._patterns.verify(suggestion)
        except Refused as refusal:
            return refusal.reason
        return None


def _row(finding: Finding, skipped_because: str | None = None) -> dict:
    row = {"column": finding.column, "kind": finding.kind, "reason": finding.reason}
    return row | ({"skipped_because": skipped_because} if skipped_because else {})
