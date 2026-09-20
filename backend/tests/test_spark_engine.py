"""What is particular to the Spark engine. Behaviour every engine shares is in test_engines.py."""

import csv
import importlib.util
import io
import logging
from pathlib import Path

import pytest
from fakes import run_replace
from test_engines import EMAIL, job_for

from domain import errors
from domain.connections import Connection, S3Credentials
from domain.jobs import JobCancelled
from infrastructure.result_store import ParquetResultStore
from infrastructure.streaming_engine import StreamingEngine

spark_engine = pytest.importorskip("infrastructure.spark_engine")

HEADER = ["id", "name", "email", "phone", "country", "signup_date", "notes"]
UNSPLIT = "unsplit (cells contain line breaks)"


def spark(tmp_path, bucket_mirror=None):
    return spark_engine.SparkEngine(
        "local[2]",
        staging_dir=tmp_path / "staging",
        source_root=bucket_mirror.as_uri() if bucket_mirror else None,
    )


def _sample_rows(count):
    """The messy customer data the demo uses, from scripts/make_sample_data.py."""
    script = Path(__file__).parents[2] / "scripts" / "make_sample_data.py"
    spec = importlib.util.spec_from_file_location("make_sample_data", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return list(module.rows(count))


def _csv(rows, header=HEADER) -> bytes:
    text = io.StringIO()
    csv.writer(text, lineterminator="\n").writerows([header, *rows])
    return text.getvalue().encode()


@pytest.fixture
def both(spark_session, connection, bucket_mirror, tmp_path):
    """Run one job on the reference engine and on Spark: ((result, columns, rows), reports)."""

    def run(job, limit=100_000):
        outcomes, reports = [], []
        engines = {"reference": StreamingEngine(), "spark": spark(tmp_path, bucket_mirror)}
        for name, engine in engines.items():
            store = ParquetResultStore(tmp_path / name)
            seen = reports if name == "spark" else []
            result = run_replace(
                engine,
                job,
                connection,
                store.path_for(job.id),
                lambda fraction, stage, seen=seen: seen.append((fraction, stage)),
            )
            outcomes.append((result, *store.read_rows(job.id, 0, limit)))
        return outcomes, reports

    return run


pytestmark = pytest.mark.spark


@pytest.mark.parametrize(
    ("pattern", "columns"),
    [
        (EMAIL, ["email", "notes"]),
        (r"\+?\d[\d\s().-]{7,}\d", []),  # phone numbers, in every column
        (r"(?i)n/a", ["email"]),
        (r"\w+", ["name"]),  # \w must cover "Zoë" in Java as it does in Python
        (r"^\s+|\s+$", ["notes"]),
        (r"\d{4}-\d{2}-\d{2}", ["signup_date"]),
    ],
)
def test_spark_and_the_reference_engine_agree_on_messy_data(both, put_object, pattern, columns):
    rows = _sample_rows(3000) + [[9001, "Zoë Müller", "ZOË@BÜCHER.DE", "", "DE", "", " padded "]]
    key = put_object("customers.csv", _csv(rows))

    (reference, spark), _ = both(job_for(key, pattern=pattern, columns=columns))

    assert spark[2] == reference[2]  # every row, in the same order
    assert spark[1] == reference[1] == HEADER
    assert spark[0] == reference[0]  # rows_total and rows_changed
    assert reference[0].rows_changed > 0  # the pattern really did something


def test_a_file_read_as_many_splits_keeps_its_row_order(both, put_object, monkeypatch, tmp_path):
    monkeypatch.setattr(spark_engine, "PARTITION_BYTES", 64 * 1024)
    key = put_object("customers.csv", _csv(_sample_rows(8000)))

    (reference, spark), _ = both(job_for(key, columns=["email"]))

    assert len(list((tmp_path / "spark" / "job").glob("*.parquet"))) > 4  # one file per split
    assert [row[0] for row in spark[2]] == [str(n) for n in range(1, 8001)]
    assert spark[2] == reference[2]


# A cell that contains a line break splits into fragments under the parallel reader. Each shape
# below puts the halves of the quote pair somewhere different.
SPLIT_SHAPES = {
    "first column": b'a,b,c\n"x\ny",2,3\n4,5,6\n',
    "middle column": b'a,b,c\n1,"x\ny",3\n4,5,6\n',
    "last column": b'a,b,c\n1,2,"x\ny"\n4,5,6\n',
    "delimiters inside": b'a,b,c\n1,"x, p\ny, q",3\n4,5,6\n',
    "escaped quotes inside": b'a,b,c\n1,"say ""hi""\nbye ""now""",3\n4,5,6\n',
    "three lines": b'a,b,c\n1,"x\nmid, dle\ny",3\n4,5,6\n',
    # Both fragments have exactly three cells, so Spark flags neither as malformed.
    "last column, fragments look well-formed": b'a,b,c\n1,2,"x\ny, q, r"\n4,5,6\n',
    "single column": b'a\n"x\ny"\nz\n',
}


@pytest.mark.parametrize("shape", SPLIT_SHAPES)
def test_cells_with_line_breaks_are_detected_and_read_again_unsplit(both, put_object, shape):
    key = put_object("c.csv", SPLIT_SHAPES[shape])

    (reference, spark), reports = both(job_for(key, pattern="nothing-matches"))

    assert spark[2] == reference[2]
    assert spark[0].rows_total == reference[0].rows_total
    assert any(UNSPLIT in stage for _, stage in reports)


def test_a_file_without_line_breaks_in_cells_is_read_once(both, put_object):
    body = b'a,b,c\n1,"quoted, comma",3\n1,2\n1,2,3,4\n"say ""hi""",2,3\n'
    (reference, spark), reports = both(job_for(put_object("c.csv", body), pattern="nothing"))

    assert spark[2] == reference[2]
    assert not any(UNSPLIT in stage for _, stage in reports)


def test_a_false_alarm_costs_a_second_pass_but_not_correctness(both, put_object):
    body = b'size,note\n1,5" pipe\n'  # an unescaped inch mark: an odd quote, but no line break
    (reference, spark), reports = both(job_for(put_object("c.csv", body), pattern="pipe"))

    assert spark[2] == reference[2] == [["1", '5" REDACTED']]
    assert any(UNSPLIT in stage for _, stage in reports)


def test_a_pattern_java_rejects_fails_with_a_clear_message(
    spark_session, connection, put_object, bucket_mirror, tmp_path
):
    key = put_object("c.csv", b"a\n1\n")
    # A named group in Python's spelling: valid at submit, invalid in the JVM.
    job = job_for(key, pattern=r"(?P<user>\w+)@")
    with pytest.raises(errors.InvalidPattern, match="Java's regex dialect.*Unknown inline"):
        run_replace(spark(tmp_path, bucket_mirror), job, connection, tmp_path / "out")


def test_column_names_need_no_quoting(both, put_object):
    names = ["First Name", "e.mail", "naïve `col`", "a,b"]
    key = put_object("c.csv", _csv([["Zoë", "z@x.com", "1", "2"]], header=names))

    (reference, spark), _ = both(job_for(key, columns=["e.mail"]))

    assert spark[1] == reference[1] == names
    assert spark[2] == reference[2] == [["Zoë", "REDACTED", "1", "2"]]


def test_glob_characters_in_a_key_are_read_literally(both, put_object):
    key = put_object("exports/data [1] {x}.csv", b"email\na@x.com\n")
    (reference, spark), _ = both(job_for(key))
    assert spark[2] == reference[2] == [["REDACTED"]]


def test_a_key_hadoop_cannot_parse_is_refused_before_spark_starts(connection, put_object, tmp_path):
    key = put_object("exports/2024-01-01T10:00:00 [v1].csv", b"email\na@x.com\n")
    with pytest.raises(errors.FileUnreadable, match="Rename the file"):
        run_replace(spark(tmp_path), job_for(key), connection, tmp_path / "out")


def test_cancel_stops_the_spark_job(spark_session, connection, put_object, bucket_mirror, tmp_path):
    key = put_object("customers.csv", _csv(_sample_rows(20_000)))
    checks = []

    def cancel_once_spark_is_running():
        checks.append(1)
        return len(checks) > 1  # the first check is before Spark starts

    with pytest.raises(JobCancelled):
        run_replace(
            spark(tmp_path, bucket_mirror),
            job_for(key),
            connection,
            tmp_path / "out" / "job",
            should_cancel=cancel_once_spark_is_running,
        )


def test_s3a_settings_carry_only_this_connections_keys():
    connection = Connection("c" * 64, "my-bucket", "eu-north-1", S3Credentials("AKIAKEY", "SECRET"))

    conf = spark_engine._s3a_conf(connection, endpoint=None)
    assert conf["fs.s3a.access.key"] == "AKIAKEY"
    assert conf["fs.s3a.secret.key"] == "SECRET"
    assert conf["fs.s3a.endpoint.region"] == "eu-north-1"
    # Never the default chain, which would fall back to the machine's own identity.
    assert conf["fs.s3a.aws.credentials.provider"].endswith("SimpleAWSCredentialsProvider")
    assert "fs.s3a.endpoint" not in conf

    fake = spark_engine._s3a_conf(connection, endpoint="http://moto:5000")
    assert fake["fs.s3a.endpoint"] == "http://moto:5000"
    assert fake["fs.s3a.path.style.access"] == "true"


@pytest.mark.parametrize(
    ("java_text", "expected"),
    [
        (
            "java.nio.file.AccessDeniedException: s3a://b/k: getFileStatus",
            errors.BucketAccessDenied,
        ),
        ("java.io.FileNotFoundException: No such file: s3a://b/k", errors.ObjectNotFound),
        ("Caused by: java.net.UnknownHostException: b.s3.amazonaws.com", errors.StorageUnreachable),
        (
            "SdkClientException: Unable to execute HTTP request: timed out",
            errors.StorageUnreachable,
        ),
        ("Cannot call methods on a stopped SparkContext.", errors.EngineUnavailable),
        # A lost master also mentions an unknown host, and must not be blamed on S3.
        (
            "All masters are unresponsive! ... java.net.UnknownHostException: spark-master",
            errors.EngineUnavailable,
        ),
    ],
)
def test_java_failures_become_domain_errors(java_text, expected):
    assert isinstance(spark_engine._translate(RuntimeError(java_text)), expected)


def test_an_unknown_java_failure_is_left_alone():
    error = RuntimeError("java.lang.OutOfMemoryError: Java heap space")
    assert spark_engine._translate(error) is error


def test_loggers_that_would_print_keys_at_debug_are_pinned():
    for name in ("boto3", "botocore", "urllib3", "py4j"):
        assert logging.getLogger(name).getEffectiveLevel() >= logging.WARNING


def test_both_engines_agree_on_several_operations_and_on_a_mapping(
    spark_session, connection, put_object, bucket_mirror, tmp_path
):
    from domain.operations import MapValues, MaskCells, Replace
    from services.pii import PATTERNS

    key = put_object("customers.csv", _csv(_sample_rows(3000)))
    operations = [
        Replace(PATTERNS["email"][1], "[EMAIL]", ["email", "notes"]),
        Replace(PATTERNS["phone"][1], "[PHONE]", ["phone", "notes"]),
        MaskCells("[NAME]", ["name"]),
        MapValues("country", {"USA": "United States", "us": "United States", "AUS": "Australia"}),
    ]
    outcomes = {}
    for name, engine in {
        "reference": StreamingEngine(),
        "spark": spark(tmp_path, bucket_mirror),
    }.items():
        store = ParquetResultStore(tmp_path / name)
        with engine.open(job_for(key), connection, lambda *_: None, lambda: False) as file:
            counts = file.distinct_values("country", 50, lambda *_: None)
            result = file.rewrite(operations, store.path_for("job"), lambda *_: None)
        outcomes[name] = (counts, result, store.read_rows("job", 0, 5000)[1])

    assert outcomes["spark"] == outcomes["reference"]
    counts, result, rows = outcomes["spark"]
    assert all(changed > 0 for changed in result.changed_by_operation)
    assert not any("@" in (row[2] or "") for row in rows)  # no e-mail address survived


def _recorder(stages):
    return lambda _fraction, stage: stages.append(stage)


def test_counting_values_notices_cells_split_over_lines(
    spark_session, connection, put_object, bucket_mirror, tmp_path
):
    body = b'id,notes,country\n1,"line one\nline two",USA\n2,plain,us\n3,"a\nb",USA\n'
    key = put_object("c.csv", body)
    seen = {}
    for name, engine in {
        "reference": StreamingEngine(),
        "spark": spark(tmp_path, bucket_mirror),
    }.items():
        stages = seen[name + " stages"] = []
        with engine.open(job_for(key), connection, lambda *_: None, lambda: False) as file:
            seen[name] = file.distinct_values("country", 10, _recorder(stages))

    assert seen["spark"] == seen["reference"] == [("USA", 2), ("us", 1)]
    assert any(UNSPLIT in stage for stage in seen["spark stages"])
