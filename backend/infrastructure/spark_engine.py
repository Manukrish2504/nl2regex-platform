"""The PySpark engine: reads the file from S3 in parallel splits and rewrites it as Parquet.

Rewriting is map-only. Every row is independent, so one input split becomes one task and one
Parquet part file, and nothing is shuffled. The one shuffle in the engine is counting a column's
distinct values, and it is small: counts are combined on each partition before they move.
"""

import io
import logging
import re
import socket
import tempfile
from collections.abc import Callable, Iterator
from contextlib import ExitStack, contextmanager, suppress
from functools import partial
from itertools import batched, islice
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
from domain.operations import MapValues, MaskCells, Operation, Replace
from domain.ports import Progress
from domain.tables import Row
from infrastructure import tabular
from infrastructure.s3_storage import read_first_lines
from infrastructure.streaming_engine import BATCH_ROWS, downloaded_excel

logger = logging.getLogger(__name__)

# Spark's default split is 128 MB. Rows stream through a task, so memory is not what decides
# this: smaller tasks mean smoother progress, cheaper task retries and better balance.
PARTITION_BYTES = 32 * 1024 * 1024
# A page read decodes one whole row group, so small groups keep paging fast on any result size.
ROW_GROUP_BYTES = 1024 * 1024
SAMPLE_ROWS = 500  # kept from an Excel file while it is converted, for OpenFile.sample()

# Java's regex engine, told to behave like Python's: (?U) makes \w, \d, \b and case-insensitive
# matching Unicode-aware, and (?d) makes "\n" the only line terminator for ".", "^" and "$".
_PYTHON_SEMANTICS = "(?Ud)"
_CORRUPT = "_corrupt"
_UNSPLIT_NOTE = ", unsplit (cells contain line breaks)"
_GLOB_CHARACTERS = re.compile(r"([\[\]{}*?\\])")

Load = Callable[[SparkSession, bool], DataFrame]


class SparkEngine:
    """One Spark application per job.

    Its session, its S3 credentials and its JVM-side caches all end with the job, so nothing
    from one connection can reach another connection's job.
    """

    def __init__(
        self,
        master: str,
        staging_dir: Path,
        conf: dict[str, str] | None = None,
        s3_endpoint: str | None = None,
        source_root: str | None = None,
    ):
        self._master = master
        self._staging_dir = staging_dir  # a disk the executors share, for a converted Excel file
        self._conf = conf or {}
        self._s3_endpoint = s3_endpoint  # only for S3-compatible stores and local fakes
        self._source_root = source_root  # tests read a local mirror of the bucket through this

    @contextmanager
    def open(
        self,
        job: Job,
        connection: Connection,
        on_progress: Progress,
        should_cancel: Callable[[], bool],
    ) -> Iterator["_SparkFile"]:
        on_progress(0.0, "Reading the header")
        with ExitStack() as cleanup:
            if job.file_format is FileFormat.CSV:
                # One small ranged GET. A bad key, a missing or empty file and a wrong encoding
                # all fail here, in milliseconds, before any JVM is started.
                head = read_first_lines(connection, job.file_key, tabular.CSV_HEAD_BYTES)
                columns, delimiter = tabular.csv_header(head)
                first_rows = tabular.csv_rows(io.BufferedReader(io.BytesIO(head)))
                next(first_rows)  # the header
                load = partial(
                    _read_csv,
                    uri=self._uri(connection, job.file_key),
                    width=len(columns),
                    delimiter=delimiter,
                )
            else:
                # Spark has no Excel reader, and an .xlsx is a zip that cannot be split anyway.
                # It becomes Parquet beside the results, on the disk Spark's executors share.
                self._staging_dir.mkdir(parents=True, exist_ok=True)
                folder = cleanup.enter_context(
                    tempfile.TemporaryDirectory(dir=self._staging_dir, prefix=f".{job.id}-")
                )
                staged = Path(folder) / "input.parquet"
                columns, first_rows = _stage_excel(
                    connection, job.file_key, staged, on_progress, should_cancel
                )
                load = partial(_read_parquet, uri=staged.as_uri())

            opened = _SparkFile(
                columns=columns,
                first_rows=first_rows,
                load=load,
                splittable=job.file_format is FileFormat.CSV,
                start_session=partial(self._session, job, connection),
                should_cancel=should_cancel,
            )
            try:
                yield opened
            finally:
                opened.close()

    def _session(self, job: Job, connection: Connection) -> SparkSession:
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
        spark.conf.set("spark.sql.files.maxPartitionBytes", str(PARTITION_BYTES))
        # Reading one column must still see whole lines, or a line with too few cells is not
        # flagged and a cell split over two lines goes unnoticed.
        spark.conf.set("spark.sql.csv.parser.columnPruning.enabled", "false")
        # Set on this session at runtime, so the keys are never part of the SparkConf, a command
        # line or the environment page, and they end with the application.
        for key, value in _s3a_conf(connection, self._s3_endpoint).items():
            spark.conf.set(key, value)
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


class _SparkFile:
    """The file, opened. Spark starts at the first pass over the data, not before: a job that
    asks a language model something first does not hold cluster cores while it waits."""

    def __init__(
        self,
        columns: list[str],
        first_rows: Iterator[Row],
        load: Load,
        splittable: bool,
        start_session: Callable[[], SparkSession],
        should_cancel: Callable[[], bool],
    ):
        self.columns = columns
        self._first_rows = first_rows
        self._load = load
        # A CSV can only be split safely if no cell spans lines. The splittable reader goes
        # first, each pass checks its own work, and once a split record is seen every pass after
        # it reads the file unsplit.
        self._passes: tuple[bool, ...] = (False, True) if splittable else (False,)
        self._start_session = start_session
        self._should_cancel = should_cancel
        self._spark: SparkSession | None = None

    def sample(self, limit: int) -> list[Row]:
        return [tabular.fit(row, len(self.columns)) for row in islice(self._first_rows, limit)]

    def distinct_values(
        self, column: str, limit: int, on_progress: Progress
    ) -> list[tuple[str | None, int]]:
        (index,) = tabular.target_indexes(self.columns, [column])
        spark = self._session(on_progress)
        for attempt, multiline in enumerate(self._passes):
            frame = self._load(spark, multiline)
            observation = Observation()
            values = frame.select(
                F.col(f"c{index}").alias("value"),
                _is_split_record(frame, len(self.columns)).alias("split"),
            ).observe(observation, F.sum(F.col("split").cast("long")).alias("split_records"))
            # The shuffle. Counts are combined on each partition first, so what moves is at most
            # (distinct values x partitions) rows, however large the file is.
            counted = (
                values.groupBy("value")
                .count()
                .orderBy(F.desc("count"), F.asc_nulls_first("value"))
                .limit(limit)
            )
            rows = self._watch(
                counted.collect, on_progress, _stage("Counting values", attempt, multiline)
            )
            if self._settled(multiline, observation):
                return [(row["value"], row["count"]) for row in rows]
        raise AssertionError("unreachable: the unsplit pass always settles")

    def rewrite(
        self, operations: list[Operation], destination: Path, on_progress: Progress
    ) -> TransformResult:
        spark = self._session(on_progress)
        for operation in operations:
            if isinstance(operation, Replace):
                _check_java_pattern(spark, operation.pattern)
        for attempt, multiline in enumerate(self._passes):
            frame, observation = _rewritten(
                spark, self._load(spark, multiline), self.columns, operations
            )
            writer = frame.write.mode("overwrite").option("parquet.block.size", ROW_GROUP_BYTES)
            self._watch(
                partial(writer.parquet, destination.as_uri()),
                on_progress,
                _stage("Transforming", attempt, multiline),
            )
            if self._settled(multiline, observation):
                metrics = observation.get
                return TransformResult(
                    metrics["rows"],
                    metrics["changed"] or 0,
                    [metrics[f"changed{number}"] or 0 for number in range(len(operations))],
                )
        raise AssertionError("unreachable: the unsplit pass always settles")

    def close(self) -> None:
        if self._spark is not None:
            _shut_down(self._spark)

    def _session(self, on_progress: Progress) -> SparkSession:
        if self._spark is None:
            if self._should_cancel():
                raise JobCancelled()
            on_progress(0.0, "Starting Spark")
            self._spark = self._start_session()
            # Reaching S3 from the JVM (a client, then the file's size) takes its own moment.
            on_progress(0.0, "Opening the file")
        return self._spark

    def _settled(self, multiline: bool, observation: Observation) -> bool:
        """False if this pass met a cell split over lines, so that it must be read again."""
        if multiline or not observation.get["split_records"]:
            return True
        logger.info("The file has cells with line breaks; reading it unsplit from here on")
        self._passes = (True,)
        return False

    def _watch[T](self, action: Callable[[], T], report: Progress, stage: str) -> T:
        """Run a Spark action on a helper thread while this thread reports progress and watches
        for a cancel. The callbacks touch the database, so they stay on the thread that owns it."""
        spark = self._spark
        outcome: list[T] = []
        failure: list[Exception] = []

        def run() -> None:
            try:
                outcome.append(action())
            except Exception as error:  # noqa: BLE001 - handed to the waiting thread below
                failure.append(error)

        report(0.0, stage)  # a second pass starts again from the beginning, and says why
        worker = InheritableThread(target=run, daemon=True)
        worker.start()
        tracker = spark.sparkContext.statusTracker()
        cancelled, furthest = False, 0.0
        while worker.is_alive():
            if not cancelled and self._should_cancel():
                cancelled = True
                spark.sparkContext.cancelAllJobs()  # this application runs one job at a time
            done = total = 0
            for stage_id in tracker.getActiveStageIds():
                info = tracker.getStageInfo(stage_id)
                if info is not None:
                    done, total = done + info.numCompletedTasks, total + info.numTasks
            if total and not cancelled:
                # A pass with a shuffle has a second, tiny stage; progress never steps back for it.
                furthest = max(furthest, done / total)
                report(furthest, f"{stage} · {done} of {total} partitions")
            worker.join(0.2)

        if cancelled:
            raise JobCancelled()
        if failure:
            raise _translate(failure[0])
        report(1.0, stage)
        return outcome[0]


def _stage(what: str, attempt: int, multiline: bool) -> str:
    """The stage shown to the user, which says so when a pass is a repeat, and why."""
    return what + (" again" if attempt else "") + (_UNSPLIT_NOTE if multiline else "")


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


def _rewritten(
    spark: SparkSession, frame: DataFrame, header: list[str], operations: list[Operation]
) -> tuple[DataFrame, Observation]:
    """The rewritten table, and an observation that fills in while that table is being written."""
    split = _is_split_record(frame, len(header))
    cells: list[Column] = [F.col(f"c{index}") for index in range(len(header))]
    changes: list[Column] = []
    for number, operation in enumerate(operations):
        changed = F.lit(False)
        for index in tabular.target_indexes(header, _columns(operation)):
            before = cells[index]
            if isinstance(operation, Replace):
                # A built-in, so it compiles into the JVM's generated code. A Python UDF would
                # ship every row to a Python process and back. The replacement is literal text:
                # Java would read "$1" as a group and "\" as an escape.
                after = F.regexp_replace(
                    before,
                    F.lit(_PYTHON_SEMANTICS + operation.pattern),
                    F.lit(operation.replacement.replace("\\", "\\\\").replace("$", "\\$")),
                )
            elif isinstance(operation, MaskCells):
                after = F.when(before.isNotNull(), F.lit(operation.replacement))
            else:
                # A broadcast join: the mapping is tiny, so every executor gets a copy and the
                # file's rows are never shuffled to meet it. A hash lookup per row, where a
                # literal map expression would scan its keys.
                lookup = _local_table(spark, operation.mapping, f"from{number}", f"to{number}")
                frame = frame.join(F.broadcast(lookup), before == F.col(f"from{number}"), "left")
                after = F.coalesce(F.col(f"to{number}"), before)
            changed = changed | ~after.eqNullSafe(before)
            cells[index] = after
        changes.append(changed)

    any_change = F.lit(False)
    for changed in changes:
        any_change = any_change | changed
    rewritten = frame.select(
        *[cell.alias(f"c{index}") for index, cell in enumerate(cells)],
        any_change.alias("changed"),
        split.alias("split"),
        *[changed.alias(f"changed{number}") for number, changed in enumerate(changes)],
    )
    observation = Observation()
    # Collected as a side effect of the write: no second pass over the data to count anything.
    observed = rewritten.observe(
        observation,
        F.count(F.lit(1)).alias("rows"),
        F.sum(F.col("changed").cast("long")).alias("changed"),
        F.sum(F.col("split").cast("long")).alias("split_records"),
        *[
            F.sum(F.col(f"changed{number}").cast("long")).alias(f"changed{number}")
            for number in range(len(changes))
        ],
    )
    named = observed.select(*[F.col(f"c{index}").alias(name) for index, name in enumerate(header)])
    return named, observation


def _local_table(spark: SparkSession, mapping: dict[str, str], key: str, value: str) -> DataFrame:
    """The mapping as a table that lives in the query plan. createDataFrame would make it an RDD,
    and broadcasting that runs a small job of its own before the real one.

    The values travel as parameters, never as SQL text, and the parameters are NAMED: PySpark
    4.1 bound positional "?" markers in reverse here, which turned {"AUS": "Australia"} into
    "us" -> "AUS" without any error. The engines' differential test is what caught it.
    """
    pairs = list(mapping.items()) or [("", "")]
    rows = ", ".join(f"(:k{n}, :v{n})" for n in range(len(pairs)))
    args = {f"k{n}": before for n, (before, _) in enumerate(pairs)}
    args |= {f"v{n}": after for n, (_, after) in enumerate(pairs)}
    return spark.sql(f"SELECT * FROM VALUES {rows} AS lookup({key}, {value})", args=args)


def _columns(operation: Operation) -> list[str]:
    return [operation.column] if isinstance(operation, MapValues) else operation.columns


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
) -> tuple[list[str], Iterator[Row]]:
    """Download the workbook and rewrite its first sheet as Parquet. Returns the column names and
    the first rows, which are kept so that a sample needs no second read."""
    first_rows: list[Row] = []
    with downloaded_excel(connection, key, on_progress) as workbook:
        rows = tabular.excel_rows(workbook)
        header = tabular.read_header(rows)
        schema = pa.schema([(f"c{index}", pa.string()) for index in range(len(header))])
        with pq.ParquetWriter(staged, schema) as writer:
            for batch in batched(rows, BATCH_ROWS):
                if should_cancel():
                    raise JobCancelled()
                fitted = [tabular.fit(row, len(header)) for row in batch]
                if len(first_rows) < SAMPLE_ROWS:
                    first_rows += fitted[: SAMPLE_ROWS - len(first_rows)]
                columns = [pa.array(column, pa.string()) for column in zip(*fitted, strict=True)]
                writer.write_table(pa.Table.from_arrays(columns, schema=schema))
    return header, iter(first_rows)


def _shut_down(spark: SparkSession) -> None:
    with suppress(Exception):
        spark.sparkContext.cancelAllJobs()
        # Hadoop caches one S3 client per bucket for the life of the JVM, and the cache key does
        # not include the credentials. Without this, a later job on a bucket of the same name
        # could read with this connection's keys.
        spark._jvm.org.apache.hadoop.fs.FileSystem.closeAll()
    spark.stop()
