import shutil
import time
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from domain.tables import Row


class ParquetResultStore:
    """A job's output is a folder of Parquet files under `root`, shared by the web and workers.

    # ponytail: a local folder, so web and workers must share a disk (one Docker volume today).
    # Move to object storage when they run on separate machines.
    """

    def __init__(self, root: Path):
        self._root = root

    def path_for(self, job_id: str) -> Path:
        return self._root / job_id

    def read_rows(self, job_id: str, offset: int, limit: int) -> tuple[list[str], list[Row]] | None:
        """Read one page by touching only the row groups that hold it.

        Parquet footers record how many rows each row group has, so the right group is found
        without reading any data, and the cost of a page does not grow with the size of the result.
        """
        folder = self.path_for(job_id)
        # Sorted by name, which is also the order engines write their part files in.
        files = sorted(folder.glob("*.parquet")) if folder.is_dir() else []
        if not files:
            return None

        # ponytail: opens every footer before the page. Write a row-count manifest next to the
        # files if a result ever has enough part files for that to show up in page latency.
        columns: list[str] = []
        pieces: list[pa.Table] = []
        skipped = wanted = 0
        for path in files:
            parquet = pq.ParquetFile(path)
            columns = columns or parquet.schema_arrow.names
            for index in range(parquet.num_row_groups):
                group_rows = parquet.metadata.row_group(index).num_rows
                if skipped + group_rows <= offset:  # the page starts after this group
                    skipped += group_rows
                    continue
                start = max(0, offset - skipped)
                piece = parquet.read_row_group(index).slice(start, limit - wanted)
                pieces.append(piece)
                wanted += piece.num_rows
                skipped += group_rows
                if wanted >= limit:
                    return columns, _rows(pieces)
        return columns, _rows(pieces)

    def delete(self, job_id: str) -> None:
        shutil.rmtree(self.path_for(job_id), ignore_errors=True)

    def purge_older_than(self, seconds: int) -> None:
        """Delete result folders past their age limit. Called when a worker starts a job."""
        if not self._root.is_dir():
            return
        cutoff = time.time() - seconds
        for folder in self._root.iterdir():
            if folder.is_dir() and folder.stat().st_mtime < cutoff:
                shutil.rmtree(folder, ignore_errors=True)


def _rows(pieces: list[pa.Table]) -> list[Row]:
    if not pieces:
        return []
    table = pa.concat_tables(pieces)
    return [
        list(row) for row in zip(*(column.to_pylist() for column in table.columns), strict=True)
    ]
