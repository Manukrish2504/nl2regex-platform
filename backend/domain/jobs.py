"""The transformation job and its lifecycle. Standard library only."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum

from domain.connections import FileFormat
from domain.errors import InvalidTransition
from domain.patterns import PatternSuggestion


class JobStatus(Enum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


ACTIVE_STATUSES = frozenset({JobStatus.QUEUED, JobStatus.RUNNING})


@dataclass
class Job:
    """One request to replace a pattern in a file. It belongs to the connection that created it."""

    id: str
    connection_id: str
    file_key: str
    file_format: FileFormat
    pattern: str  # empty until a worker has written it, when the job was given a prompt instead
    replacement: str  # always literal text, never a template with backreferences
    columns: list[str]  # empty means every column
    created_at: datetime
    prompt: str | None = None  # the plain-English request, if the pattern was not typed
    explanation: str | None = None  # what the written pattern matches, in one sentence
    pattern_source: str = "user"  # "user", "llm", or "cache" for an llm answer served again
    status: JobStatus = JobStatus.QUEUED
    progress: int = 0  # percent
    stage: str = "Waiting for a worker"
    attempts: int = 0
    cancel_requested: bool = False
    error_code: str | None = None
    error_message: str | None = None
    rows_total: int | None = None
    rows_changed: int | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None

    @property
    def is_active(self) -> bool:
        return self.status in ACTIVE_STATUSES

    def is_stale(self, now: datetime, limit: timedelta) -> bool:
        """Running for longer than any worker is allowed to: whoever ran it was killed."""
        return (
            self.status is JobStatus.RUNNING
            and self.started_at is not None
            and now - self.started_at > limit
        )

    @property
    def needs_pattern(self) -> bool:
        return bool(self.prompt) and not self.pattern

    def adopt(self, suggestion: PatternSuggestion, from_cache: bool) -> None:
        """Take the pattern written for this job's prompt.

        A request such as "replace emails in the Email column with REDACTED" also states a
        replacement and a column. Those fill a field the user left empty, and never override one
        the user filled in.
        """
        self.pattern = suggestion.pattern
        self.explanation = suggestion.explanation
        self.pattern_source = "cache" if from_cache else "llm"
        if not self.replacement and suggestion.replacement:
            self.replacement = suggestion.replacement
        if not self.columns and suggestion.columns:
            self.columns = list(suggestion.columns)

    def start(self, now: datetime) -> None:
        """Begin an attempt. From RUNNING this is a takeover after the previous worker died."""
        self._require(JobStatus.QUEUED, JobStatus.RUNNING)
        self.status = JobStatus.RUNNING
        self.attempts += 1
        self.started_at = now
        self.progress = 0
        self.stage = "Starting"

    def succeed(self, now: datetime, rows_total: int, rows_changed: int) -> None:
        self._require(JobStatus.RUNNING)
        self.status = JobStatus.SUCCESS
        self.progress = 100
        self.stage = "Done"
        self.rows_total = rows_total
        self.rows_changed = rows_changed
        self.finished_at = now

    def fail(self, now: datetime, code: str, message: str) -> None:
        self._require(JobStatus.QUEUED, JobStatus.RUNNING)
        self.status = JobStatus.FAILED
        self.stage = "Failed"
        self.error_code = code
        self.error_message = message
        self.finished_at = now

    def cancel(self, now: datetime) -> None:
        self._require(JobStatus.QUEUED, JobStatus.RUNNING)
        self.status = JobStatus.CANCELLED
        self.stage = "Cancelled"
        self.finished_at = now

    def requeue_for_retry(self, reason: str) -> None:
        self._require(JobStatus.RUNNING)
        self.status = JobStatus.QUEUED
        self.progress = 0
        self.stage = f"Retrying: {reason}"

    def _require(self, *allowed: JobStatus) -> None:
        if self.status not in allowed:
            raise InvalidTransition(f"A {self.status.value} job cannot change like this.")


@dataclass(frozen=True)
class TransformResult:
    rows_total: int
    rows_changed: int


class JobCancelled(Exception):
    """Raised by an engine when it notices the cancel request. A signal, not a failure."""


class RetryLater(Exception):
    """Raised by the job service after re-queueing a job, asking the task layer to retry it."""
