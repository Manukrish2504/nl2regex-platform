"""Use-cases for jobs: the API side (submit, read, cancel) and the worker side (run)."""

import logging
import re
import time
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from domain.connections import FileFormat
from domain.errors import (
    ConnectionNotFound,
    DomainError,
    InvalidPattern,
    JobNotFinished,
    JobNotFound,
    ResultsExpired,
    StorageUnreachable,
    TooManyActiveJobs,
    UnsupportedFile,
)
from domain.jobs import Job, JobCancelled, JobStatus, RetryLater
from domain.ports import JobRepository, ResultStore, TaskQueue, TransformEngine
from domain.tables import Page
from services.connections import ConnectionService

logger = logging.getLogger(__name__)

# A failure worth trying again. Everything else (bad credentials, a missing column) fails at once.
TRANSIENT_ERRORS = (StorageUnreachable,)


def utc_now() -> datetime:
    return datetime.now(UTC)


class JobService:
    def __init__(
        self,
        connections: ConnectionService,
        jobs: JobRepository,
        queue: TaskQueue,
        engine: TransformEngine,
        results: ResultStore,
        *,
        max_active_jobs: int,
        max_attempts: int,
        stale_after: timedelta,
        results_max_age: timedelta,
        clock: Callable[[], datetime] = utc_now,
    ):
        self._connections = connections
        self._jobs = jobs
        self._queue = queue
        self._engine = engine
        self._results = results
        self._max_active_jobs = max_active_jobs
        self._max_attempts = max_attempts
        self._stale_after = stale_after
        self._results_max_age = results_max_age
        self._now = clock

    # --- the API side ---------------------------------------------------------------------

    def submit(
        self, token: str | None, file_key: str, pattern: str, replacement: str, columns: list[str]
    ) -> Job:
        """Validate, persist as QUEUED and hand to a worker. Returns without doing the work."""
        connection = self._connections.get(token)
        file_format = FileFormat.from_key(file_key)
        if file_format is None:
            raise UnsupportedFile()
        try:
            re.compile(pattern)
        except re.error as error:
            raise InvalidPattern(str(error)) from error
        if self._jobs.count_active(connection.id) >= self._max_active_jobs:
            raise TooManyActiveJobs()

        job = Job(
            id=str(uuid.uuid4()),
            connection_id=connection.id,
            file_key=file_key,
            file_format=file_format,
            pattern=pattern,
            replacement=replacement,
            columns=columns,
            created_at=self._now(),
        )
        self._jobs.add(job)
        self._queue.enqueue_job(job.id)
        return job

    def get(self, token: str | None, job_id: str) -> Job:
        return self._owned(token, job_id)

    def recent(self, token: str | None, limit: int = 50) -> list[Job]:
        connection = self._connections.get(token)
        return [
            self._fail_if_stale(job) for job in self._jobs.list_for_connection(connection.id, limit)
        ]

    def cancel(self, token: str | None, job_id: str) -> Job:
        """Cancel a queued job at once, or ask a running one to stop. Idempotent once finished."""
        job = self._owned(token, job_id)
        if job.status is JobStatus.QUEUED:
            if self._change(job, lambda: job.cancel(self._now())):
                return job
            job = self._owned(token, job_id)  # a worker picked it up in between
        if job.status is JobStatus.RUNNING:
            self._jobs.request_cancel(job.id)
            job = self._owned(token, job_id)
        return job

    def read_page(self, token: str | None, job_id: str, page: int, page_size: int) -> Page:
        job = self._owned(token, job_id)
        if job.status is not JobStatus.SUCCESS:
            raise JobNotFinished()
        found = self._results.read_rows(job.id, offset=(page - 1) * page_size, limit=page_size)
        if found is None:
            raise ResultsExpired()
        columns, rows = found
        return Page(columns, rows, page, page_size, total_rows=job.rows_total or 0)

    def forget_jobs(self, token: str | None) -> None:
        """Part of disconnecting: stop this connection's jobs and delete what they produced."""
        try:
            connection = self._connections.get(token)
        except ConnectionNotFound:
            return  # already expired: nothing of theirs is reachable any more
        for job in self._jobs.list_for_connection(connection.id, limit=1000):
            if job.status is JobStatus.RUNNING:
                self._jobs.request_cancel(job.id)
            elif job.status is JobStatus.QUEUED:
                self._change(job, lambda job=job: job.cancel(self._now()))
            self._results.delete(job.id)

    # --- the worker side ------------------------------------------------------------------

    def run(self, job_id: str, redelivered: bool = False) -> None:
        """Run one attempt of a job. Called by the Celery task, never by the API."""
        job = self._jobs.get(job_id)
        if job is None:
            return
        # The broker redelivers a message only when its previous delivery was never acknowledged,
        # which means that worker died. A job found RUNNING on a first delivery is a duplicate.
        taking_over = job.status is JobStatus.RUNNING and redelivered
        if job.status is not JobStatus.QUEUED and not taking_over:
            return
        if job.attempts >= self._max_attempts:
            self._change(
                job,
                lambda: job.fail(
                    self._now(), "too_many_attempts", f"The job failed {job.attempts} times."
                ),
            )
            return
        if not self._change(job, lambda: job.start(self._now())):
            return  # another worker won the race for this job

        self._results.purge_older_than(int(self._results_max_age.total_seconds()))
        self._results.delete(job.id)  # a clean slate, so a re-run never mixes with an old one
        try:
            connection = self._connections.get_by_id(job.connection_id)
            result = self._engine.run(
                job,
                connection,
                self._results.path_for(job.id),
                on_progress=self._progress_writer(job),
                should_cancel=self._cancel_checker(job.id),
            )
        except JobCancelled:
            self._results.delete(job.id)
            self._change(job, lambda: job.cancel(self._now()))
        except TRANSIENT_ERRORS as error:
            reason = error.message  # `error` itself is deleted when this block ends
            self._results.delete(job.id)
            if job.attempts >= self._max_attempts:
                self._fail(job, error.code, f"{reason} Gave up after {job.attempts} tries.")
                return
            self._change(job, lambda: job.requeue_for_retry(reason))
            raise RetryLater(reason) from error
        except DomainError as error:
            self._results.delete(job.id)
            self._fail(job, error.code, error.message)
        else:
            changed = self._change(
                job, lambda: job.succeed(self._now(), result.rows_total, result.rows_changed)
            )
            if not changed:  # it was marked failed or cancelled while the engine finished
                self._results.delete(job.id)

    def fail_unexpected(self, job_id: str, code: str, message: str) -> None:
        """For the task layer: an attempt ended in a way no use-case anticipated."""
        job = self._jobs.get(job_id)
        if job is not None and job.is_active:
            self._results.delete(job.id)
            self._fail(job, code, message)

    # --- helpers --------------------------------------------------------------------------

    def _owned(self, token: str | None, job_id: str) -> Job:
        connection = self._connections.get(token)
        job = self._jobs.get(job_id)
        # Someone else's job looks exactly like a missing one.
        if job is None or job.connection_id != connection.id:
            raise JobNotFound()
        return self._fail_if_stale(job)

    def _fail_if_stale(self, job: Job) -> Job:
        """A hard time limit kills the worker without a trace, so staleness is judged on read."""
        if job.is_stale(self._now(), self._stale_after):
            self._fail(job, "timed_out", "The job ran past its time limit and was stopped.")
        return job

    def _fail(self, job: Job, code: str, message: str) -> None:
        self._change(job, lambda: job.fail(self._now(), code, message))

    def _change(self, job: Job, change: Callable[[], None]) -> bool:
        """Apply a status change and persist it only if nobody else changed the job first."""
        expected_status, expected_attempts = job.status, job.attempts
        change()
        saved = self._jobs.save(job, expected_status, expected_attempts)
        if not saved:
            logger.info("Job %s changed elsewhere; dropped a move to %s", job.id, job.status.value)
        return saved

    def _progress_writer(self, job: Job) -> Callable[[float, str], None]:
        """Persist progress at most once a second, and always when the stage changes."""
        last = {"at": 0.0, "stage": ""}

        def write(fraction: float, stage: str) -> None:
            # Keep the worker's own copy current too, so a job that is later cancelled or fails
            # is saved with the progress it reached, not with zero.
            job.progress, job.stage = min(99, max(0, int(fraction * 100))), stage
            now = time.monotonic()
            if stage == last["stage"] and now - last["at"] < 1.0:
                return
            last.update(at=now, stage=stage)
            self._jobs.save_progress(job.id, job.progress, stage)

        return write

    def _cancel_checker(self, job_id: str) -> Callable[[], bool]:
        """Ask the database whether a cancel was requested, at most five times a second.

        The query is a primary-key existence check, so this costs little, and it bounds how long
        a user waits after pressing Cancel to a fifth of a second plus one batch.
        """
        last = {"at": 0.0, "value": False}

        def check() -> bool:
            now = time.monotonic()
            if not last["value"] and now - last["at"] >= 0.2:
                last.update(at=now, value=self._jobs.is_cancel_requested(job_id))
            return last["value"]

        return check
