"""What can be done to a file's cells. A job is a list of these, applied in order.

Column names are as a person (or a language model) wrote them. The engine resolves them against
the file's header, exact names first, then ignoring case, spaces, underscores and hyphens.
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Replace:
    """Replace every match of a regex in the chosen columns. Empty `columns` means all of them."""

    pattern: str
    replacement: str  # literal text, never a template with group references
    columns: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class MaskCells:
    """Replace the whole of every non-blank cell: for a column that is sensitive as such, like a
    name, which no pattern can recognise."""

    replacement: str
    columns: list[str]


@dataclass(frozen=True)
class MapValues:
    """Replace a cell that equals a key with that key's value. Other cells, and blanks, stay."""

    column: str
    mapping: dict[str, str]


Operation = Replace | MaskCells | MapValues
