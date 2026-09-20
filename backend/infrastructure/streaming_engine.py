import io
import re
import tempfile
from collections import Counter
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from itertools import batched, islice
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from domain.connections import Connection, FileFormat
from domain.errors import FileTooLarge
from domain.jobs import Job, JobCancelled, TransformResult
from domain.operations import MapValues, MaskCells, Operation, Replace
from domain.ports import Progress
from domain.tables import Row
from infrastructure import tabular
from infrastructure.s3_storage import open_object, read_first_lines, translated_errors

BATCH_ROWS = 10_000  # also the Parquet row-group size, which is what makes page reads cheap
_DOWNLOAD_CHUNK = 1024 * 1024

CellChange = Callable[[str | None], str | None]


class StreamingEngine:
    """Rewrites a file in one process, a batch of rows at a time, holding one batch in memory.

    # ponytail: single process, so throughput is one core. The Spark engine replaces this for
    # scale behind the same TransformEngine port; this one remains as the reference in tests.
    """

    @contextmanager
    def open(
        self,
        job: Job,
        connection: Connection,
        on_progress: Progress,
        should_cancel: Callable[[], bool],
    ) -> Iterator["_StreamedFile"]:
        on_progress(0.0, "Reading the header")
        if job.file_format is FileFormat.CSV:
            head = read_first_lines(connection, job.file_key, tabular.CSV_HEAD_BYTES)
            columns, _ = tabular.csv_header(head)
            first_rows = tabular.csv_rows(io.BufferedReader(io.BytesIO(head)))
            next(first_rows)  # the header
            yield _StreamedFile(columns, first_rows, should_cancel, connection, job.file_key)
            return
        with downloaded_excel(connection, job.file_key, on_progress) as workbook:
            rows = tabular.excel_rows(workbook)
            columns = tabular.read_header(rows)
            yield _StreamedFile(columns, rows, should_cancel, workbook=workbook)


class _StreamedFile:
    def __init__(
        self,
        columns: list[str],
        first_rows: Iterator[Row],
        should_cancel: Callable[[], bool],
        connection: Connection | None = None,
        key: str = "",
        workbook: Path | None = None,
    ):
        self.columns = columns
        self._first_rows = first_rows
        self._should_cancel = should_cancel
        self._connection, self._key, self._workbook = connection, key, workbook

    def sample(self, limit: int) -> list[Row]:
        return [tabular.fit(row, len(self.columns)) for row in islice(self._first_rows, limit)]

    def distinct_values(
        self, column: str, limit: int, on_progress: Progress
    ) -> list[tuple[str | None, int]]:
        (index,) = tabular.target_indexes(self.columns, [column])
        counts: Counter[str | None] = Counter()
        with self._rows(on_progress, "Counting values") as rows:
            for batch in batched(rows, BATCH_ROWS):
                if self._should_cancel():
                    raise JobCancelled()
                counts.update(tabular.fit(row, len(self.columns))[index] for row in batch)
        # Most frequent first, and by value among equals, so every engine gives the same list.
        return sorted(counts.items(), key=lambda item: (-item[1], item[0] or ""))[:limit]

    def rewrite(
        self, operations: list[Operation], destination: Path, on_progress: Progress
    ) -> TransformResult:
        steps = [
            (_change(operation), tabular.target_indexes(self.columns, _columns(operation)))
            for operation in operations
        ]
        schema = pa.schema([(name, pa.string()) for name in self.columns])
        rows_total = rows_changed = 0
        changed_by_operation = [0] * len(operations)

        destination.mkdir(parents=True, exist_ok=True)
        with (
            self._rows(on_progress, "Transforming") as rows,
            pq.ParquetWriter(destination / "part-00000.parquet", schema) as writer,
        ):
            for batch in batched(rows, BATCH_ROWS):
                if self._should_cancel():
                    raise JobCancelled()
                fitted = [tabular.fit(row, len(self.columns)) for row in batch]
                for row in fitted:
                    row_changed = False
                    for number, (change, targets) in enumerate(steps):
                        touched = False
                        for index in targets:
                            new = change(row[index])
                            # "Changed" means the text differs, not that a pattern matched.
                            touched = touched or new != row[index]
                            row[index] = new
                        changed_by_operation[number] += touched
                        row_changed = row_changed or touched
                    rows_changed += row_changed
                columns = [pa.array(column, pa.string()) for column in zip(*fitted, strict=True)]
                writer.write_table(pa.Table.from_arrays(columns, schema=schema))
                rows_total += len(fitted)
        return TransformResult(rows_total, rows_changed, changed_by_operation)

    @contextmanager
    def _rows(self, on_progress: Progress, stage: str) -> Iterator[Iterator[Row]]:
        """Every row after the header, from the start, reporting how far through the file it is."""
        if self._workbook is not None:
            # ponytail: no progress while a workbook is read, because a read-only workbook does
            # not reliably know its row count. Excel tops out near a million rows.
            on_progress(0.0, stage)
            rows = tabular.excel_rows(self._workbook)
            tabular.read_header(rows)
            yield rows
            return
        body, size = open_object(self._connection, self._key)
        # A dropped connection can surface at any read, long after the object was opened.
        with translated_errors(self._connection.bucket):
            counting = _CountingReader(body, size, lambda done: on_progress(done, stage))
            rows = tabular.csv_rows(io.BufferedReader(counting, buffer_size=1024 * 1024))
            tabular.read_header(rows)
            yield rows


def _columns(operation: Operation) -> list[str]:
    return [operation.column] if isinstance(operation, MapValues) else operation.columns


def _change(operation: Operation) -> CellChange:
    """What one operation does to one cell. A blank cell is never changed."""
    if isinstance(operation, Replace):
        pattern, replacement = re.compile(operation.pattern), operation.replacement
        # A function replacement is inserted as-is, so "\\1" or "$1" in it stay literal text.
        return lambda cell: pattern.sub(lambda _match: replacement, cell) if cell else cell
    if isinstance(operation, MaskCells):
        return lambda cell: operation.replacement if cell else cell
    return lambda cell: operation.mapping.get(cell, cell) if cell else cell


@contextmanager
def downloaded_excel(connection: Connection, key: str, on_progress: Progress) -> Iterator[Path]:
    """The workbook as a local file, for as long as the block runs. An .xlsx is a zip archive, so
    nothing can be read from it until all of it has arrived."""
    body, size = open_object(connection, key)
    if size > tabular.EXCEL_MAX_BYTES:
        raise FileTooLarge()
    with tempfile.NamedTemporaryFile(suffix=".xlsx") as local:
        with translated_errors(connection.bucket):
            downloaded = 0
            for chunk in body.iter_chunks(_DOWNLOAD_CHUNK):
                local.write(chunk)
                downloaded += len(chunk)
                on_progress(downloaded / max(size, 1), "Downloading")
        local.flush()
        yield Path(local.name)


class _CountingReader(io.RawIOBase):
    """Adapts botocore's StreamingBody to a file object, reporting the fraction read so far."""

    def __init__(self, body, size: int, on_fraction: Callable[[float], None]):
        self._body = body
        self._size = max(size, 1)
        self._read = 0
        self._on_fraction = on_fraction

    def readable(self) -> bool:
        return True

    def readinto(self, buffer) -> int:
        data = self._body.read(len(buffer))
        buffer[: len(data)] = data
        self._read += len(data)
        self._on_fraction(self._read / self._size)
        return len(data)
