"""What any engine must do. Every case here runs on the reference engine and on Spark, so each
one is also a check that the two agree."""

import io
from datetime import UTC, datetime

import pytest
from openpyxl import Workbook

from domain import errors
from domain.connections import FileFormat
from domain.jobs import Job, JobCancelled
from infrastructure import streaming_engine
from infrastructure.result_store import ParquetResultStore
from infrastructure.streaming_engine import StreamingEngine

EMAIL = r"[\w.+-]+@[\w-]+\.[\w.]+"


def job_for(key, pattern=EMAIL, replacement="REDACTED", columns=()):
    return Job(
        id="job",
        connection_id="a" * 64,
        file_key=key,
        file_format=FileFormat.from_key(key),
        pattern=pattern,
        replacement=replacement,
        columns=list(columns),
        created_at=datetime(2026, 9, 20, tzinfo=UTC),
    )


@pytest.fixture(params=["streaming", pytest.param("spark", marks=pytest.mark.spark)])
def engine(request, bucket_mirror):
    if request.param == "streaming":
        return StreamingEngine()
    request.getfixturevalue("spark_session")
    from infrastructure.spark_engine import SparkEngine

    return SparkEngine(master="local[2]", source_root=bucket_mirror.as_uri())


@pytest.fixture
def run(engine, connection, tmp_path):
    """Run the engine on a job and return (result, columns, rows, progress reports)."""
    store = ParquetResultStore(tmp_path / "out")

    def run_job(job, should_cancel=lambda: False):
        reports = []
        result = engine.run(
            job,
            connection,
            store.path_for(job.id),
            lambda f, stage: reports.append((f, stage)),
            should_cancel,
        )
        columns, rows = store.read_rows(job.id, 0, 1000)
        return result, columns, rows, reports

    run_job.store = store
    return run_job


def test_the_example_from_the_brief(run, put_object):
    key = put_object(
        "brief.csv",
        b"ID,Name,Email\n1,John Doe,john.doe@example.com\n2,Jane Smith,jane_smith@domain.com\n"
        b"3,Alice Brown,alice.brown@website.org\n",
    )
    result, columns, rows, _ = run(job_for(key, columns=["Email"]))

    assert columns == ["ID", "Name", "Email"]
    assert rows == [
        ["1", "John Doe", "REDACTED"],
        ["2", "Jane Smith", "REDACTED"],
        ["3", "Alice Brown", "REDACTED"],
    ]
    assert (result.rows_total, result.rows_changed) == (3, 3)


def test_only_the_chosen_columns_change(run, put_object):
    key = put_object("c.csv", b"email,notes\na@x.com,write to b@y.org\n,nothing here\n")
    _, _, rows, _ = run(job_for(key, columns=["email"]))
    assert rows == [["REDACTED", "write to b@y.org"], [None, "nothing here"]]


def test_empty_cells_are_none_whether_quoted_or_not(run, put_object):
    key = put_object("c.csv", b'a,b,c\n1,,3\n1,"",3\n,,\n')
    _, _, rows, _ = run(job_for(key, pattern="nothing-matches"))
    assert rows == [["1", None, "3"], ["1", None, "3"], [None, None, None]]


def test_blank_lines_are_not_rows(run, put_object):
    key = put_object("c.csv", b"\na,b\n\n1,2\n\n\n3,4\n")
    result, columns, rows, _ = run(job_for(key, pattern="nothing-matches"))
    assert (columns, rows, result.rows_total) == (["a", "b"], [["1", "2"], ["3", "4"]], 2)


def test_rows_changed_counts_rows_whose_text_changed(run, put_object):
    key = put_object("c.csv", b"v\nsame\nother\n")
    # The pattern matches both rows, but replacing "same" with "same" changes nothing.
    result, _, _, _ = run(job_for(key, pattern="same|other", replacement="same"))
    assert (result.rows_total, result.rows_changed) == (2, 1)


def test_no_columns_chosen_means_every_column(run, put_object):
    key = put_object("c.csv", b"email,notes\na@x.com,write to b@y.org\n")
    result, _, rows, _ = run(job_for(key))
    assert rows == [["REDACTED", "write to REDACTED"]]
    assert result.rows_changed == 1  # rows, not cells


def test_values_are_never_reinterpreted(run, put_object):
    key = put_object("c.csv", b"zip,amount,flag\n00123,1.50,TRUE\n")
    _, _, rows, _ = run(job_for(key, pattern="nothing-matches"))
    assert rows == [["00123", "1.50", "TRUE"]]  # not 123, not 1.5, not True


def test_quoted_commas_line_breaks_and_quotes_survive(run, put_object):
    key = put_object("c.csv", b'id,notes\n1,"Smith, John said ""hi""\nmail a@x.com"\n2,plain\n')
    _, _, rows, _ = run(job_for(key))
    assert rows == [["1", 'Smith, John said "hi"\nmail REDACTED'], ["2", "plain"]]


def test_byte_order_mark_and_unicode(run, put_object):
    key = put_object("c.csv", "﻿name,email\nZoë Müller,zoë@bücher.de\n".encode())
    _, columns, rows, _ = run(job_for(key, pattern=r"\S+@\S+"))
    assert columns == ["name", "email"]  # the BOM is not part of the first column's name
    assert rows == [["Zoë Müller", "REDACTED"]]


def test_semicolon_and_tab_delimiters_are_detected(run, put_object):
    for name, body in [
        ("s.csv", b"id;email\n1;a@x.com\n2;b@y.org\n"),
        ("t.csv", b"id\temail\n1\ta@x.com\n"),
    ]:
        _, columns, rows, _ = run(job_for(put_object(name, body)))
        assert columns == ["id", "email"]
        assert rows[0] == ["1", "REDACTED"]


def test_ragged_rows_are_padded_and_trimmed_like_spark_does(run, put_object):
    key = put_object("c.csv", b"a,b,c\n1,2\n1,2,3,4\n")
    _, _, rows, _ = run(job_for(key, pattern="nothing-matches"))
    assert rows == [["1", "2", None], ["1", "2", "3"]]


def test_blank_and_duplicate_column_names_are_made_usable(run, put_object):
    key = put_object("c.csv", b"email,,email\na@x.com,b,c@z.com\n")
    _, columns, rows, _ = run(job_for(key, columns=["email_2"]))
    assert columns == ["email", "column_2", "email_2"]
    assert rows == [["a@x.com", "b", "REDACTED"]]


def test_the_replacement_is_literal_text(run, put_object):
    key = put_object("c.csv", b"email\na@x.com\n")
    for replacement in [r"\1", "$1", r"\g<0>", ""]:
        _, _, rows, _ = run(job_for(key, pattern=r"(\w+)@x\.com", replacement=replacement))
        assert rows == [[replacement or ""]]


def test_a_header_only_file_gives_an_empty_result(run, put_object):
    result, columns, rows, _ = run(job_for(put_object("c.csv", b"id,email\n")))
    assert (result.rows_total, columns, rows) == (0, ["id", "email"], [])


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        (b"", errors.FileUnreadable),
        (b"name\n\xff\xfe broken\n", errors.FileUnreadable),  # not UTF-8
    ],
)
def test_unreadable_files_fail_with_a_clear_error(run, put_object, body, expected):
    with pytest.raises(expected):
        run(job_for(put_object("c.csv", body)))


def test_a_missing_column_is_named_in_the_error(run, put_object):
    key = put_object("c.csv", b"id,email\n1,a@x.com\n")
    with pytest.raises(errors.ColumnNotFound, match="'emial'"):
        run(job_for(key, columns=["emial"]))


def test_a_missing_file_is_reported(run, s3_bucket):
    with pytest.raises(errors.ObjectNotFound):
        run(job_for("samples/deleted-meanwhile.csv"))


def test_progress_only_moves_forward_and_reaches_the_end(run, put_object, monkeypatch):
    monkeypatch.setattr(streaming_engine, "BATCH_ROWS", 100)
    body = b"id,email\n" + b"".join(b"%d,user%d@example.com\n" % (n, n) for n in range(2000))
    result, _, rows, reports = run(job_for(put_object("big.csv", body)))

    fractions = [fraction for fraction, _ in reports]
    assert fractions == sorted(fractions)
    assert fractions[-1] == pytest.approx(1.0)
    assert (result.rows_total, len(rows)) == (2000, 1000)  # read_rows was capped at 1000 here


def test_the_reference_engine_stops_between_batches(run, engine, put_object, monkeypatch):
    if not isinstance(engine, StreamingEngine):
        pytest.skip("Spark's cancel path has its own test")
    monkeypatch.setattr(streaming_engine, "BATCH_ROWS", 100)
    body = b"id\n" + b"".join(b"%d\n" % n for n in range(1000))
    checks = []

    def cancel_on_the_third_check():
        checks.append(1)
        return len(checks) >= 3

    with pytest.raises(JobCancelled):
        run(job_for(put_object("big.csv", body)), should_cancel=cancel_on_the_third_check)
    assert len(checks) == 3  # it stopped at once, not at the end of the file


def test_excel_files_are_read_as_text(run, put_object):
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["id", "email", "joined"])
    sheet.append([1, "a@x.com", datetime(2024, 3, 12)])
    sheet.append([None, None, None])  # a blank row in the middle of the sheet
    sheet.append([2, None, "unknown"])
    buffer = io.BytesIO()
    workbook.save(buffer)

    result, columns, rows, reports = run(job_for(put_object("book.xlsx", buffer.getvalue())))
    assert columns == ["id", "email", "joined"]
    assert rows == [["1", "REDACTED", "2024-03-12 00:00:00"], ["2", None, "unknown"]]
    assert result.rows_total == 2
    assert "Downloading" in {stage for _, stage in reports}


def test_an_oversized_excel_file_is_refused_before_downloading(run, put_object, monkeypatch):
    from infrastructure import tabular

    monkeypatch.setattr(tabular, "EXCEL_MAX_BYTES", 10)
    with pytest.raises(errors.FileTooLarge):
        run(job_for(put_object("book.xlsx", b"x" * 100)))


def test_a_corrupt_excel_file_is_reported(run, put_object):
    with pytest.raises(errors.FileUnreadable):
        run(job_for(put_object("book.xlsx", b"this is not a zip archive")))
