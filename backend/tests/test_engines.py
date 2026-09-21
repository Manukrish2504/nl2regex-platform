"""What any engine must do. Every case here runs on the reference engine and on Spark, so each
one is also a check that the two agree."""

import io
from datetime import datetime

import pytest
from fakes import EMAIL, job_for, run_replace
from openpyxl import Workbook

from domain import errors
from domain.jobs import JobCancelled
from domain.operations import MapValues, MaskCells, Replace
from infrastructure import streaming_engine
from infrastructure.result_store import ParquetResultStore
from infrastructure.streaming_engine import StreamingEngine


@pytest.fixture(params=["streaming", pytest.param("spark", marks=pytest.mark.spark)])
def engine(request, bucket_mirror, tmp_path):
    if request.param == "streaming":
        return StreamingEngine()
    request.getfixturevalue("spark_session")
    from infrastructure.spark_engine import SparkEngine

    return SparkEngine(
        "local[2]", staging_dir=tmp_path / "staging", source_root=bucket_mirror.as_uri()
    )


@pytest.fixture
def run(engine, connection, tmp_path):
    """Run the engine on a job and return (result, columns, rows, progress reports)."""
    store = ParquetResultStore(tmp_path / "out")

    def run_job(job, should_cancel=lambda: False):
        reports = []
        result = run_replace(
            engine,
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


def test_a_column_is_found_whatever_its_case_spacing_or_underscores(run, put_object):
    key = put_object("c.csv", b"First_Name,E-Mail,email\nZoe,a@x.com,b@y.org\n")
    # "email" names the column spelt exactly that way, not the look-alike before it.
    _, _, rows, _ = run(job_for(key, pattern="[a-z]+", columns=["first name", "email"]))
    assert rows == [["ZREDACTED", "a@x.com", "REDACTED@REDACTED.REDACTED"]]

    _, _, rows, _ = run(job_for(key, pattern="[a-z]+", columns=["e mail"]))
    assert rows == [["Zoe", "REDACTED@REDACTED.REDACTED", "b@y.org"]]


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


# --- more than one operation, and the other kinds of operation -------------------------------

MESSY = (
    b"id,name,email,country,notes\n"
    b"1,John Doe,john@x.com,USA,write to j.doe@y.org\n"
    b"2,Jane Smith,,us,nothing here\n"
    b"3,Zoe Brown,zoe@z.io,Germany,\n"
    b"4,,n/a,Atlantis,call me\n"
)


@pytest.fixture
def opened(engine, connection, put_object):
    """Open MESSY with the engine under test: opened(operations...) -> (result, rows)."""
    key = put_object("messy.csv", MESSY)

    def rewrite(*operations, tmp=None):
        store = ParquetResultStore(tmp)
        with engine.open(job_for(key), connection, lambda *_: None, lambda: False) as file:
            result = file.rewrite(list(operations), store.path_for("job"), lambda *_: None)
        return result, store.read_rows("job", 0, 100)[1]

    return rewrite


def test_operations_are_applied_in_order_and_counted_one_by_one(opened, tmp_path):
    result, rows = opened(
        Replace(EMAIL, "[EMAIL]", ["email", "notes"]),
        MaskCells("[NAME]", ["name"]),
        tmp=tmp_path / "out",
    )
    assert rows == [
        ["1", "[NAME]", "[EMAIL]", "USA", "write to [EMAIL]"],
        ["2", "[NAME]", None, "us", "nothing here"],
        ["3", "[NAME]", "[EMAIL]", "Germany", None],
        ["4", None, "n/a", "Atlantis", "call me"],  # a blank cell is never masked
    ]
    assert (result.rows_total, result.rows_changed) == (4, 3)
    assert result.changed_by_operation == [2, 3]  # rows each operation changed


def test_a_mapping_changes_the_values_it_names_and_leaves_the_rest(opened, tmp_path):
    mapping = {"USA": "United States", "us": "United States"}
    result, rows = opened(MapValues("country", mapping), tmp=tmp_path / "out")

    assert [row[3] for row in rows] == ["United States", "United States", "Germany", "Atlantis"]
    assert [row[0] for row in rows] == ["1", "2", "3", "4"]  # the join kept the rows in order
    assert result.changed_by_operation == [2]


def test_a_later_operation_sees_what_an_earlier_one_wrote(opened, tmp_path):
    _, rows = opened(
        Replace("USA|us", "US", ["country"]),
        MapValues("country", {"US": "United States"}),
        tmp=tmp_path / "out",
    )
    assert [row[3] for row in rows] == ["United States", "United States", "Germany", "Atlantis"]


def test_distinct_values_come_with_counts_most_frequent_first(engine, connection, put_object):
    body = b"id,country\n" + b"".join(
        f"{n},{value}\n".encode()
        for n, value in enumerate(["us"] * 5 + ["USA"] * 3 + [""] * 3 + ["UK"])
    )
    key = put_object("c.csv", body)
    with engine.open(job_for(key), connection, lambda *_: None, lambda: False) as file:
        assert file.columns == ["id", "country"]
        counts = file.distinct_values("Country", 10, lambda *_: None)  # found whatever its case
        limited = file.distinct_values("country", 2, lambda *_: None)

    assert counts == [("us", 5), (None, 3), ("USA", 3), ("UK", 1)]  # ties: blank, then by value
    assert limited == counts[:2]


def test_the_first_rows_can_be_sampled_without_a_pass_over_the_file(engine, connection, put_object):
    key = put_object("messy.csv", MESSY)
    with engine.open(job_for(key), connection, lambda *_: None, lambda: False) as file:
        sample = file.sample(2)
    assert sample == [
        ["1", "John Doe", "john@x.com", "USA", "write to j.doe@y.org"],
        ["2", "Jane Smith", None, "us", "nothing here"],
    ]


def test_a_follow_up_reads_what_an_earlier_job_wrote(engine, connection, put_object, tmp_path):
    """The second request runs on the first one's output, not on the file in the bucket."""
    key = put_object("c.csv", b"id,email,notes\n1,a@x.com,call 555-123-4567\n2,b@y.org,nothing\n")
    store = ParquetResultStore(tmp_path / "out")
    job = job_for(key, columns=["email"])

    with engine.open(job, connection, lambda *_: None, lambda: False) as first:
        first.rewrite(
            [Replace(EMAIL, "[EMAIL]", ["email"])], store.path_for("first"), lambda *_: None
        )

    # Now follow it up, reading the result folder instead of the bucket.
    with engine.open(
        job, connection, lambda *_: None, lambda: False, source=store.path_for("first")
    ) as second:
        assert second.columns == ["id", "email", "notes"]
        assert second.sample(1) == [["1", "[EMAIL]", "call 555-123-4567"]]
        result = second.rewrite(
            [Replace(r"\d{3}-\d{3}-\d{4}", "[PHONE]", ["notes"])],
            store.path_for("second"),
            lambda *_: None,
        )

    assert (result.rows_total, result.rows_changed) == (2, 1)
    assert store.read_rows("second", 0, 10)[1] == [
        ["1", "[EMAIL]", "call [PHONE]"],
        ["2", "[EMAIL]", "nothing"],
    ]


def test_a_follow_up_can_count_values_too(engine, connection, put_object, tmp_path):
    key = put_object("c.csv", b"id,country\n1,USA\n2,us\n3,USA\n")
    store = ParquetResultStore(tmp_path / "out")
    job = job_for(key, pattern="nothing-matches")

    with engine.open(job, connection, lambda *_: None, lambda: False) as first:
        first.rewrite([job.as_replace()], store.path_for("first"), lambda *_: None)
    with engine.open(
        job, connection, lambda *_: None, lambda: False, source=store.path_for("first")
    ) as second:
        counts = second.distinct_values("country", 10, lambda *_: None)

    assert counts == [("USA", 2), ("us", 1)]
