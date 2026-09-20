"""Slices of tabular data. Every cell is text or None, by design: nothing is type-converted."""

from dataclasses import dataclass

from domain.errors import ColumnNotFound

Row = list[str | None]


@dataclass(frozen=True)
class FilePreview:
    """The column names and first rows of a source file."""

    columns: list[str]
    rows: list[Row]


@dataclass(frozen=True)
class Page:
    """One page of a finished job's output."""

    columns: list[str]
    rows: list[Row]
    page: int
    page_size: int
    total_rows: int


def column_indexes(header: list[str], wanted: list[str]) -> list[int]:
    """Positions of the wanted columns. An empty request means every column.

    An exact name wins. Failing that, case, spaces, underscores and hyphens are ignored, so a
    request that says "the email column" finds `Email`, and "first name" finds `First_Name`. A
    name that still matches nothing is an error; it never quietly means "every column".
    """
    if not wanted:
        return list(range(len(header)))
    loosely = {_loose(name): index for index, name in reversed(list(enumerate(header)))}
    indexes, missing = [], []
    for name in wanted:
        index = header.index(name) if name in header else loosely.get(_loose(name))
        if index is None:
            missing.append(name)
        elif index not in indexes:
            indexes.append(index)
    if missing:
        raise ColumnNotFound(missing)
    return indexes


def _loose(name: str) -> str:
    return "".join(character for character in name.casefold() if character not in " _-")
