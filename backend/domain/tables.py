"""Slices of tabular data. Every cell is text or None, by design: nothing is type-converted."""

from dataclasses import dataclass

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
