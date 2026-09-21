"""What the application needs from the outside world. Infrastructure implements these."""

from collections.abc import Callable
from contextlib import AbstractContextManager
from pathlib import Path
from typing import Protocol

from domain.advice import ColumnProfile, Finding
from domain.connections import Connection, FileFormat, FileListing, S3Credentials
from domain.jobs import Job, JobStatus, TransformResult
from domain.operations import Operation
from domain.patterns import PatternSuggestion, Rejection
from domain.tables import FilePreview, Row


class ObjectStorage(Protocol):
    def resolve_bucket(self, credentials: S3Credentials, bucket: str) -> str:
        """Prove the credentials can list the bucket and return its region. Raises a DomainError."""
        ...

    def list_files(
        self, connection: Connection, prefix: str, page_token: str | None
    ) -> FileListing:
        """One page of the folders and files directly under `prefix`."""
        ...


class CredentialVault(Protocol):
    def store(self, connection: Connection) -> None: ...

    def load(self, connection_id: str) -> Connection | None:
        """The connection, or None if it is unknown, expired or fails its integrity check."""
        ...

    def delete(self, connection_id: str) -> None: ...


class JobRepository(Protocol):
    def add(self, job: Job) -> None: ...

    def get(self, job_id: str) -> Job | None: ...

    def save(self, job: Job, expected_status: JobStatus, expected_attempts: int) -> bool:
        """Write the job only if its stored status and attempts still match (compare-and-set).

        Returns False when someone else changed the job first. Never writes cancel_requested.
        """
        ...

    def save_progress(self, job_id: str, progress: int, stage: str) -> None:
        """Update the progress columns of a RUNNING job, and nothing else."""
        ...

    def request_cancel(self, job_id: str) -> bool:
        """Flag a RUNNING job for cancellation. False if it is not running."""
        ...

    def is_cancel_requested(self, job_id: str) -> bool: ...

    def list_for_connection(self, connection_id: str, limit: int) -> list[Job]: ...

    def count_active(self, connection_id: str) -> int: ...


class TaskQueue(Protocol):
    """Hands work to background workers. Only IDs travel, never credentials."""

    def enqueue_job(self, job_id: str) -> None: ...

    def enqueue_preview(self, connection_id: str, file_key: str) -> None: ...


Progress = Callable[[float, str], None]  # a fraction from 0 to 1, and a short stage name


class OpenFile(Protocol):
    """One file, opened for one job. Everything a transformation needs from an engine.

    Every method raises JobCancelled once the job's cancel request is seen, and a DomainError for
    anything the user can fix.
    """

    columns: list[str]

    def sample(self, limit: int) -> list[Row]:
        """The first rows, without reading the rest of the file."""
        ...

    def distinct_values(
        self, column: str, limit: int, on_progress: Progress
    ) -> list[tuple[str | None, int]]:
        """The column's values with how many rows hold each, most frequent first, at most `limit`.
        A full pass over the file."""
        ...

    def rewrite(
        self, operations: list[Operation], destination: Path, on_progress: Progress
    ) -> TransformResult:
        """Apply the operations, in order, and write Parquet files into `destination`."""
        ...


class TransformEngine(Protocol):
    def open(
        self,
        job: Job,
        connection: Connection,
        on_progress: Progress,
        should_cancel: Callable[[], bool],
        source: Path | None = None,
    ) -> AbstractContextManager[OpenFile]:
        """Whatever the engine starts for a job (a Spark application, a download) lives exactly
        as long as this context, however many passes over the file the job makes inside it.

        `source` is an earlier job's output folder, for a follow-up. Without it the job reads
        its file from the bucket.
        """
        ...


class ResultStore(Protocol):
    def path_for(self, job_id: str) -> Path: ...

    def read_rows(self, job_id: str, offset: int, limit: int) -> tuple[list[str], list[Row]] | None:
        """Column names and up to `limit` rows from `offset`, or None if the results are gone."""
        ...

    def delete(self, job_id: str) -> None: ...

    def purge_older_than(self, seconds: int) -> None: ...


class FileInspector(Protocol):
    def preview(
        self, connection: Connection, file_key: str, file_format: FileFormat
    ) -> FilePreview:
        """Column names and the first rows, reading as little of the file as possible."""
        ...


class PreviewStore(Protocol):
    """Short-lived storage for previews built in the background. Entries are plain dicts."""

    def get(self, connection_id: str, file_key: str) -> dict | None: ...

    def mark_pending(self, connection_id: str, file_key: str) -> bool:
        """Claim the preview. False if another request already did, so it is enqueued only once."""
        ...

    def put(self, connection_id: str, file_key: str, entry: dict) -> None: ...


class PatternWriter(Protocol):
    """A language model that writes a regex from a request. It sees the request and nothing else:
    no column names, no rows. The user's data never leaves for a third party."""

    is_configured: bool  # False when there is no API key: requests must then be refused up front

    def write(self, request: str, rejected: Rejection | None = None) -> PatternSuggestion:
        """Raises PatternNotUnderstood if the request does not describe something to find."""
        ...


class PatternCache(Protocol):
    """So that an identical request is not sent to the language model twice."""

    def get(self, request: str) -> PatternSuggestion | None: ...

    def put(self, request: str, suggestion: PatternSuggestion) -> None: ...


class PatternProbe(Protocol):
    def check(self, pattern: str) -> None:
        """Raises UnsafePattern if the pattern could take exponentially long on some input."""
        ...


class PiiClassifier(Protocol):
    """A language model that says which columns hold personal data. It is shown column names and
    the shapes of values, never a value."""

    def classify(self, profiles: list[ColumnProfile]) -> list[Finding]: ...


class ValueStandardiser(Protocol):
    """A language model that maps the spellings of one column to canonical values. It is shown
    that column's distinct values and nothing else from the file."""

    def standardise(
        self, column: str, values: list[str], instruction: str | None
    ) -> list[tuple[str, str]]:
        """Pairs of (a value as it is, the value it should become)."""
        ...


class AdviceCache(Protocol):
    """So that the same question about the same input is not sent to the language model twice."""

    def get(self, key: str) -> dict | None: ...

    def put(self, key: str, advice: dict) -> None: ...
