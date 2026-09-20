import io
import re
import tempfile
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from itertools import batched
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from domain.connections import Connection, FileFormat
from domain.errors import FileTooLarge
from domain.jobs import Job, JobCancelled, TransformResult
from domain.tables import Row
from infrastructure import tabular
from infrastructure.s3_storage import open_object, translated_errors

BATCH_ROWS = 10_000  # also the Parquet row-group size, which is what makes page reads cheap
_DOWNLOAD_CHUNK = 1024 * 1024

Progress = Callable[[float, str], None]


class StreamingEngine:
    """Rewrites a file in one process, a batch of rows at a time, holding one batch in memory.

    # ponytail: single process, so throughput is one core. The Spark engine replaces this for
    # scale behind the same TransformEngine port; this one remains as the reference in tests.
    """

    def run(
        self,
        job: Job,
        connection: Connection,
        destination: Path,
        on_progress: Progress,
        should_cancel: Callable[[], bool],
    ) -> TransformResult:
        pattern = re.compile(job.pattern)

        def replace(cell: str | None) -> tuple[str | None, bool]:
            if not cell:
                return cell, False
            # A function replacement is inserted as-is, so "\1" or "$1" in it stay literal text.
            replaced = pattern.sub(lambda _match: job.replacement, cell)
            # "Changed" means the text differs, not merely that the pattern matched.
            return replaced, replaced != cell

        rows_total = rows_changed = 0
        with source_rows(connection, job.file_key, job.file_format, on_progress) as rows:
            header = tabular.read_header(rows)
            targets = tabular.target_indexes(header, job.columns)
            schema = pa.schema([(name, pa.string()) for name in header])

            destination.mkdir(parents=True, exist_ok=True)
            with pq.ParquetWriter(destination / "part-00000.parquet", schema) as writer:
                for batch in batched(rows, BATCH_ROWS):
                    if should_cancel():
                        raise JobCancelled()
                    fitted = [tabular.fit(row, len(header)) for row in batch]
                    for row in fitted:
                        changed = False
                        for index in targets:
                            row[index], cell_changed = replace(row[index])
                            changed = changed or cell_changed
                        rows_changed += changed
                    columns = [
                        pa.array(column, pa.string()) for column in zip(*fitted, strict=True)
                    ]
                    writer.write_table(pa.Table.from_arrays(columns, schema=schema))
                    rows_total += len(fitted)
        return TransformResult(rows_total, rows_changed)


@contextmanager
def source_rows(
    connection: Connection, key: str, file_format: FileFormat, on_progress: Progress
) -> Iterator[Iterator[Row]]:
    """The file's rows, reporting progress as the bytes (CSV) or rows (Excel) are consumed."""
    body, size = open_object(connection, key)
    # A dropped connection can surface at any read, long after the object was opened.
    with translated_errors(connection.bucket):
        if file_format is FileFormat.CSV:
            counting = _CountingReader(body, size, lambda done: on_progress(done, "Transforming"))
            yield tabular.csv_rows(io.BufferedReader(counting, buffer_size=1024 * 1024))
            return

        if size > tabular.EXCEL_MAX_BYTES:
            raise FileTooLarge()
        with tempfile.NamedTemporaryFile(suffix=".xlsx") as local:
            downloaded = 0
            for chunk in body.iter_chunks(_DOWNLOAD_CHUNK):
                local.write(chunk)
                downloaded += len(chunk)
                on_progress(0.5 * downloaded / max(size, 1), "Downloading")
            local.flush()
            # An .xlsx is a zip archive, so nothing can be read until all of it has arrived.
            # ponytail: progress holds at 50% while the rows are rewritten, because a read-only
            # workbook does not reliably know its row count. Excel tops out near a million rows.
            on_progress(0.5, "Transforming")
            yield tabular.excel_rows(Path(local.name))


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
