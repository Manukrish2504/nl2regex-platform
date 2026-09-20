import os
import time

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from infrastructure.result_store import ParquetResultStore


@pytest.fixture
def store(tmp_path):
    return ParquetResultStore(tmp_path / "results")


def write_parts(store, job_id, part_sizes, row_group_size=10):
    """Several part files of several row groups each, numbered 0..n, like a Spark job's output."""
    folder = store.path_for(job_id)
    folder.mkdir(parents=True)
    number = 0
    for part, size in enumerate(part_sizes):
        ids = [str(n) for n in range(number, number + size)]
        table = pa.table(
            {"id": ids, "note": [None if int(n) % 7 == 0 else f"note {n}" for n in ids]}
        )
        pq.write_table(table, folder / f"part-{part:05d}.parquet", row_group_size=row_group_size)
        number += size


@pytest.mark.parametrize(
    ("offset", "limit", "expected_ids"),
    [
        (0, 5, range(0, 5)),  # inside the first row group
        (8, 5, range(8, 13)),  # across a row-group boundary
        (22, 6, range(22, 28)),  # across a part-file boundary (the first file holds 25 rows)
        (0, 60, range(0, 60)),  # every group of every file
        (55, 50, range(55, 60)),  # the last, short page
        (60, 10, range(0)),  # exactly past the end
        (500, 10, range(0)),  # far past the end
    ],
)
def test_pages_come_back_in_order_across_row_groups_and_files(store, offset, limit, expected_ids):
    write_parts(store, "job", part_sizes=[25, 20, 15])
    columns, rows = store.read_rows("job", offset, limit)

    assert columns == ["id", "note"]
    assert [row[0] for row in rows] == [str(n) for n in expected_ids]


def test_empty_cells_stay_empty(store):
    write_parts(store, "job", part_sizes=[10])
    _, rows = store.read_rows("job", 0, 10)
    assert rows[0] == ["0", None]
    assert rows[1] == ["1", "note 1"]


def test_a_page_reads_only_the_row_groups_it_needs(store, monkeypatch):
    write_parts(store, "job", part_sizes=[100], row_group_size=10)
    read = []
    original = pq.ParquetFile.read_row_group
    monkeypatch.setattr(
        pq.ParquetFile,
        "read_row_group",
        lambda self, index, *args, **kwargs: (
            read.append(index) or original(self, index, *args, **kwargs)
        ),
    )
    store.read_rows("job", offset=45, limit=10)
    assert read == [4, 5]  # rows 45-54 live in groups 4 and 5; the other eight were never read


def test_a_result_with_no_rows_is_an_empty_page_not_a_missing_one(store):
    write_parts(store, "job", part_sizes=[0])
    assert store.read_rows("job", 0, 10) == (["id", "note"], [])


def test_missing_results_are_reported_as_none(store):
    assert store.read_rows("never-ran", 0, 10) is None
    write_parts(store, "job", part_sizes=[5])
    store.delete("job")
    assert store.read_rows("job", 0, 10) is None
    store.delete("job")  # deleting twice is fine


def test_purge_removes_only_old_results(store):
    write_parts(store, "old", part_sizes=[5])
    write_parts(store, "new", part_sizes=[5])
    nine_hours_ago = time.time() - 9 * 3600
    os.utime(store.path_for("old"), (nine_hours_ago, nine_hours_ago))

    store.purge_older_than(8 * 3600)
    assert store.read_rows("old", 0, 1) is None
    assert store.read_rows("new", 0, 1) is not None

    ParquetResultStore(store.path_for("nowhere")).purge_older_than(1)  # no folder yet: no error
