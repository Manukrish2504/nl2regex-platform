"""The PySpark engine: reads the file from S3 in parallel splits and rewrites it as Parquet.

The plan is map-only. Every row is independent, so one input split becomes one task and one
Parquet part file, and nothing is ever shuffled.
"""

import logging
import re
import socket
import tempfile
from collections.abc import Callable
from contextlib import ExitStack, suppress
from functools import partial
from itertools import batched
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
from pyspark import InheritableThread
from pyspark.errors import IllegalArgumentException
from pyspark.sql import Column, DataFrame, Observation, SparkSession
from pyspark.sql import functions as F
from pyspark.sql.types import StringType, StructField, StructType

from domain.connections import Connection, FileFormat
from domain.errors import (
    BucketAccessDenied,
    DomainError,
    EngineUnavailable,
    FileUnreadable,
    InvalidPattern,
    ObjectNotFound,
    StorageUnreachable,
)
from domain.jobs import Job, JobCancelled, TransformResult
from infrastructure import tabular
from infrastructure.s3_storage import read_first_lines
from infrastructure.streaming_engine import BATCH_ROWS, source_rows

logger = logging.getLogger(__name__)

# Spark's default split is 128 MB. Rows stream through a task, so memory is not what decides
# this: smaller tasks mean smoother progress, cheaper task retries and better balance.
PARTITION_BYTES = 32 * 1024 * 1024
# A page read decodes one whole row group, so small groups keep paging fast on any result size.
ROW_GROUP_BYTES = 1024 * 1024

# Java's regex engine, told to behave like Python's: (?U) makes \w, \d, \b and case-insensitive
# matching Unicode-aware, and (?d) makes "\n" the only line terminator for ".", "^" and "$".
_PYTHON_SEMANTICS = "(?Ud)"
_CORRUPT = "_corrupt"
_UNSPLIT_STAGE = "Transforming again, unsplit (cells contain line breaks)"
_GLOB_CHARACTERS = re.compile(r"([\[\]{}*?\\])")

Progress = Callable[[float, str], None]
Load = Callable[[SparkSession, bool], DataFrame]


class SparkEngine:
    """One Spark application per job.

    Its session, its S3 credentials and its JVM-side caches all end with the job, so nothing
    from one connection can reach another connection's job.
    """

    def __init__(
        self,
        master: str,
        conf: dict[str, str] | None = None,
        s3_endpoint: str | None = None,
        source_root: str | None = None,
    ):
        self._master = master
        self._conf = conf or {}
        self._s3_endpoint = s3_endpoint  # only for S3-compatible stores and local fakes
        self._source_root = source_root  # tests read a local mirror of the bucket through this

    def run(
        self,
        job: Job,
        connection: Connection,
        destination: Path,
        on_progress: Progress,
        should_cancel: Callable[[], bool],
    ) -> TransformResult:
        on_progress(0.0, "Reading the header")
        with ExitStack() as cleanup:
            if job.file_format is FileFormat.CSV:
                # One small ranged GET. A bad key, a missing or empty file and a wrong encoding
                # all fail here, in milliseconds, before any JVM is started.
                head = read_first_lines(connection, job.file_key, tabular.CSV_HEAD_BYTES)
                header, delimiter = tabular.csv_header(head)
                load = partial(
                    _read_csv,
                    uri=self._uri(connection, job.file_key),
                    width=len(header),
                    delimiter=delimiter,
                )
                # The splittable reader goes first; the unsplit one runs only if it is needed.
                passes, start = (False, True), 0.0
            else:
                # Spark has no Excel reader, and an .xlsx is a zip that cannot be split anyway.
                # It becomes Parquet beside the results, on the disk Spark's executors share.
                destination.parent.mkdir(parents=True, exist_ok=True)
                folder = cleanup.enter_context(
                    tempfile.TemporaryDirectory(dir=destination.parent, prefix=f".{job.id}-")
                )
                staged = Path(folder) / "input.parquet"
                header = _stage_excel(connection, job.file_key, staged, on_progress, should_cancel)
                load = partial(_read_parquet, uri=staged.as_uri())
                passes, start = (False,), 0.5

            targets = tabular.target_indexes(header, job.columns)
            if should_cancel():
                raise JobCancelled()
            on_progress(start, "Starting Spark")

            def report(fraction: float, stage: str) -> None:
                on_progress(start + (1 - start) * fraction, stage)

            spark = self._session(job)
            try:
                # Reaching S3 from the JVM (a client, then the file's size) takes its own moment.
                on_progress(start, "Opening the file")
                _check_java_pattern(spark, job.pattern)
                spark.conf.set("spark.sql.files.maxPartitionBytes", str(PARTITION_BYTES))
                # Set on this session at runtime, so the keys are never part of the SparkConf, a
                # command line or the environment page, and they end with the application.
                for key, value in _s3a_conf(connection, self._s3_endpoint).items():
                    spark.conf.set(key, value)

                for multiline in passes:
                    frame, observation = _rewrite(
                        load(spark, multiline), header, targets, job.pattern, job.replacement
                    )
                    stage = _UNSPLIT_STAGE if multiline else "Transforming"
                    _write(spark, frame, destination, should_cancel, report, stage)
                    metrics = observation.get
                    if multiline or not metrics["split_records"]:
                        break
                    logger.info("Job %s has cells with line breaks; reading it unsplit", job.id)
                return TransformResult(metrics["rows"], metrics["changed"] or 0)
            finally:
                _shut_down(spark)

    def _session(self, job: Job) -> SparkSession:
        builder = (
            SparkSession.builder.master(self._master)
            .appName(f"nl2regex-{job.id}")
            .config("spark.ui.showConsoleProgress", "false")
        )
        if not self._master.startswith("local"):
            # Executors connect back to the driver, so it advertises an address they can reach.
            builder = builder.config(
                "spark.driver.host", socket.gethostbyname(socket.gethostname())
            )
        for key, value in self._conf.items():
            builder = builder.config(key, value)
        try:
            spark = builder.getOrCreate()
        except Exception as error:  # a master that cannot be reached surfaces here
            raise _translate(error) from None
        spark.sparkContext.setLogLevel("WARN")
        return spark

    def _uri(self, connection: Connection, key: str) -> str:
        root = self._source_root or f"s3a://{connection.bucket}"
        # Spark expands glob characters in a path, so they are escaped to be read literally.
        literal_key, globbed = _GLOB_CHARACTERS.subn(r"\\\1", key)
        if globbed and ":" in key:
            # Hadoop's glob matcher takes "10:00 [v1].csv" for a URI with the scheme "10". Either
            # character alone is read fine; found by trying it against a real s3a connection.
            raise FileUnreadable(
                "Spark cannot open a file whose name has both a colon and one of [ ] { } * ? "
                "in it. Rename the file and try again."
            )
        return f"{root}/{literal_key}"


def _s3a_conf(connection: Connection, endpoint: str | None) -> dict[str, str]:
    conf = {
        # Only the user's own keys. The default provider chain would fall back to whatever
        # identity the machine has (an instance role, say) and read with the platform's rights.
        "fs.s3a.aws.credentials.provider": "org.apache.hadoop.fs.s3a.SimpleAWSCredentialsProvider",
        "fs.s3a.access.key": connection.credentials.access_key_id,
        "fs.s3a.secret.key": connection.credentials.secret_access_key,
        # Known since the connection was made, so s3a needs no permission to look it up.
        "fs.s3a.endpoint.region": connection.region,
    }
    if endpoint:
        conf |= {"fs.s3a.endpoint": endpoint, "fs.s3a.path.style.access": "true"}
        if endpoint.startswith("http://"):
            conf["fs.s3a.connection.ssl.enabled"] = "false"
    return conf


def _check_java_pattern(spark: SparkSession, pattern: str) -> None:
    """The pattern passed Python's compiler at submit. Java's dialect differs in places."""
    try:
        spark._jvm.java.util.regex.Pattern.compile(pattern)
    except IllegalArgumentException as error:  # how PySpark surfaces PatternSyntaxException
        reason = (str(error).splitlines() or ["no reason given"])[0].strip()
        raise InvalidPattern(
            f"Java's regex dialect, which the Spark engine uses, rejects it ({reason})"
        ) from error


def _read_parquet(spark: SparkSession, _multiline: bool, uri: str) -> DataFrame:
    return spark.read.parquet(uri)


def _read_csv(
    spark: SparkSession, multiline: bool, uri: str, width: int, delimiter: str
) -> DataFrame:
    # Every column is text: a cleaning tool must not turn 00123 into 123. Columns are named by
    # position here, so a header with spaces, dots or backticks never needs quoting; the real
    # names are applied when the result is written.
    schema = StructType(
        [StructField(f"c{index}", StringType()) for index in range(width)]
        + [StructField(_CORRUPT, StringType())]
    )
    return spark.read.csv(
        uri,
        schema=schema,
        header=True,
        sep=delimiter,
        quote='"',
        escape='"',  # "" is an escaped quote (RFC 4180). Spark's default, a backslash, mangles it.
        multiLine=multiline,
        mode="PERMISSIVE",  # short rows are padded with nulls and long rows trimmed
        columnNameOfCorruptRecord=_CORRUPT,
    )


def _rewrite(
    frame: DataFrame, header: list[str], targets: list[int], pattern: str, replacement: str
) -> tuple[DataFrame, Observation]:
    """The rewritten table, and an observation that fills in while that table is being written."""
    java_pattern = F.lit(_PYTHON_SEMANTICS + pattern)
    # The replacement is literal text. Java would read "$1" as a group and "\" as an escape.
    java_replacement = F.lit(replacement.replace("\\", "\\\\").replace("$", "\\$"))

    cells: list[Column] = []
    changed = F.lit(False)
    for index in range(len(header)):
        cell = F.col(f"c{index}")
        if index in targets:
            # A built-in, so it compiles into the JVM's generated code. A Python UDF would ship
            # every row to a Python process and back.
            replaced = F.regexp_replace(cell, java_pattern, java_replacement)
            changed = changed | ~replaced.eqNullSafe(cell)
            cell = replaced
        cells.append(cell.alias(f"c{index}"))

    rewritten = frame.select(
        *cells, changed.alias("changed"), _is_split_record(frame, len(header)).alias("split")
    )
    observation = Observation()
    # Collected as a side effect of the write: no second pass over the data to count anything.
    observed = rewritten.observe(
        observation,
        F.count(F.lit(1)).alias("rows"),
        F.sum(F.col("changed").cast("long")).alias("changed"),
        F.sum(F.col("split").cast("long")).alias("split_records"),
    )
    named = observed.select(*[F.col(f"c{index}").alias(name) for index, name in enumerate(header)])
    return named, observation


def _is_split_record(frame: DataFrame, width: int) -> Column:
    """True for a row that is a fragment of a record whose cell contains a line break.

    A CSV can only be split safely when no cell spans lines, and that cannot be known without
    reading it. So the splittable reader goes first and this checks its work. A fragment holds
    one half of a pair of quotes, which shows in one of two places:
      - Spark flags the row as malformed, and its raw text has an odd number of quotes;
      - the row has the right number of cells, which takes a broken cell in the last column,
        and then the closing quote is left inside that last cell.
    A false alarm (an unescaped inch mark, say) only costs the slower second pass.
    """
    if _CORRUPT not in frame.columns:
        return F.lit(False)  # Parquet input: there are no lines to split

    def odd_quotes(column: Column) -> Column:
        quotes = F.length(column) - F.length(F.replace(column, F.lit('"'), F.lit("")))
        return F.coalesce(quotes % 2 == 1, F.lit(False))

    return odd_quotes(F.col(_CORRUPT)) | odd_quotes(F.col(f"c{width - 1}"))


def _write(
    spark: SparkSession,
    frame: DataFrame,
    destination: Path,
    should_cancel: Callable[[], bool],
    report: Progress,
    stage: str,
) -> None:
    """Run the write on a helper thread while this thread reports progress and watches for a
    cancel. The callbacks touch the database, so they stay on the thread that owns it."""
    failure: list[Exception] = []

    def write() -> None:
        try:
            writer = frame.write.mode("overwrite").option("parquet.block.size", ROW_GROUP_BYTES)
            writer.parquet(destination.as_uri())
        except Exception as error:  # noqa: BLE001 - handed to the waiting thread below
            failure.append(error)

    report(0.0, stage)  # a second pass starts again from the beginning, and says why
    worker = InheritableThread(target=write, daemon=True)
    worker.start()
    tracker = spark.sparkContext.statusTracker()
    cancelled = False
    while worker.is_alive():
        if not cancelled and should_cancel():
            cancelled = True
            spark.sparkContext.cancelAllJobs()  # this application runs exactly one job
        done = total = 0
        for stage_id in tracker.getActiveStageIds():
            info = tracker.getStageInfo(stage_id)
            if info is not None:
                done, total = done + info.numCompletedTasks, total + info.numTasks
        if total and not cancelled:
            report(done / total, f"{stage} · {done} of {total} partitions")
        worker.join(0.2)

    if cancelled:
        raise JobCancelled()
    if failure:
        raise _translate(failure[0])
    report(1.0, "Finishing")


# ponytail: Java failures are recognised by class name in the error text, because PySpark hands
# over a string and a stack trace. Anything unrecognised stays an internal error.
_JAVA_FAILURES: tuple[tuple[str, type[DomainError]], ...] = (
    # The cluster first: a driver that cannot find its master also mentions an unknown host.
    # It gives up on a master it cannot register with, and stops its own context.
    ("All masters are unresponsive", EngineUnavailable),
    ("stopped SparkContext", EngineUnavailable),
    ("SparkContext was shut down", EngineUnavailable),
    ("AccessDeniedException", BucketAccessDenied),
    ("FileNotFoundException", ObjectNotFound),
    ("UnknownHostException", StorageUnreachable),
    ("ConnectException", StorageUnreachable),
    ("ConnectTimeoutException", StorageUnreachable),
    ("SocketTimeoutException", StorageUnreachable),
    ("NoRouteToHostException", StorageUnreachable),
    ("Unable to execute HTTP request", StorageUnreachable),
)


def _translate(error: Exception) -> Exception:
    text = str(error)
    for marker, domain_error in _JAVA_FAILURES:
        if marker in text:
            logger.warning("Spark job failed: %s", marker)  # the marker only, never the text
            return domain_error()
    return error


def _stage_excel(
    connection: Connection,
    key: str,
    staged: Path,
    on_progress: Progress,
    should_cancel: Callable[[], bool],
) -> list[str]:
    """Download the workbook and rewrite its first sheet as Parquet. Returns the column names."""
    with source_rows(connection, key, FileFormat.EXCEL, on_progress) as rows:
        header = tabular.read_header(rows)
        schema = pa.schema([(f"c{index}", pa.string()) for index in range(len(header))])
        with pq.ParquetWriter(staged, schema) as writer:
            for batch in batched(rows, BATCH_ROWS):
                if should_cancel():
                    raise JobCancelled()
                fitted = [tabular.fit(row, len(header)) for row in batch]
                columns = [pa.array(column, pa.string()) for column in zip(*fitted, strict=True)]
                writer.write_table(pa.Table.from_arrays(columns, schema=schema))
    return header


def _shut_down(spark: SparkSession) -> None:
    with suppress(Exception):
        spark.sparkContext.cancelAllJobs()
        # Hadoop caches one S3 client per bucket for the life of the JVM, and the cache key does
        # not include the credentials. Without this, a later job on a bucket of the same name
        # could read with this connection's keys.
        spark._jvm.org.apache.hadoop.fs.FileSystem.closeAll()
    spark.stop()
