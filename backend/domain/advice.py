"""What a language model is shown about a file, and what it says back. Standard library only.

Neither type can carry a cell's value. A profile holds shapes ("aaaa.aaa@aaaaaaa.aaa"), and a
finding names a column and a kind of data.
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ColumnProfile:
    column: str
    blank_share: float  # 0 to 1, of the sampled rows
    shapes: list[str]  # the most common shapes of its values, most common first
    # The most common shapes of the words inside its values that are not plain words. In free
    # text every value has a shape of its own, so an e-mail address buried in a sentence never
    # shows in `shapes`; here it does, as "aaaa99@aaaa.aa".
    token_shapes: list[str]


@dataclass(frozen=True)
class Finding:
    """One kind of personal data in one column."""

    column: str
    kind: str  # "email", "phone", "name", ... or "other"
    reason: str
    # Only for "other": a pattern the model wrote, and its own test cases for it.
    pattern: str | None = None
    should_match: list[str] = field(default_factory=list)
    should_not_match: list[str] = field(default_factory=list)
