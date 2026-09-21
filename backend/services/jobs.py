"""Use-cases for jobs: the API side (submit, read, cancel) and the worker side (run)."""

import logging
import re
import time
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

from domain.connections import FileFormat
from domain.errors import (
    ConnectionNotFound,
    DomainError,
    EngineUnavailable,
    FileTooLarge,
    InvalidPattern,
    JobNotFinished,
    JobNotFound,
    LLMNotConfigured,
    LLMUnavailable,
    ResultsExpired,
    SourceJobUnusable,
    StorageUnreachable,
    TooManyActiveJobs,
    UnsupportedFile,
)
from domain.jobs import Job, JobCancelled, JobStatus, RetryLater, needs_model
from domain.operations import Operation
from domain.ports import (
    JobRepository,
    ObjectStorage,
    OpenFile,
    Progress,
    ResultStore,
    TaskQueue,
    TransformEngine,
)
from domain.tables import Page
from services.connections import ConnectionService
from services.patterns import PatternService
from services.pii import SAMPLE_ROWS, PiiService
from services.standardise import MAX_VALUES, StandardiseService

logger = logging.getLogger(__name__)

# Failures worth trying again. Everything else (bad credentials, a missing column) fails at once.
TRANSIENT_ERRORS = (StorageUnreachable, EngineUnavailable, LLMUnavailable)


def utc_now() -> datetime:
    return datetime.now(UTC)


class JobService:
    def __init__(
        self,
        connections: ConnectionService,
        jobs: JobRepository,
        queue: TaskQueue,
        storage: ObjectStorage,
        engine: TransformEngine,
        results: ResultStore,
        patterns: PatternService,
        pii: PiiService,
        standardiser: StandardiseService,
        *,
        max_active_jobs: int,
        max_attempts: int,
        max_file_bytes: int,
        stale_after: timedelta,
        results_max_age: timedelta,
        clock: Callable[[], datetime] = utc_now,
    ):
        self._connections = connections
        self._jobs = jobs
        self._queue = queue
        self._storage = storage
        self._engine = engine
        self._results = results
        self._patterns = patterns
        self._pii = pii
        self._standardiser = standardiser
        self._max_active_jobs = max_active_jobs
        self._max_attempts = max_attempts
        self._max_file_bytes = max_file_bytes
        self._stale_after = stale_after
        self._results_max_age = results_max_age
        self._now = clock

    # --- the API side ---------------------------------------------------------------------

    def submit(
        self,
        token: str | None,
        replacement: str,
        columns: list[str],
        pattern: str = "",
        prompt: str | None = None,
        kind: str = "replace",
        file_key: str = "",
        source_job_id: str | None = None,
    ) -> Job:
        """Validate, persist as QUEUED and hand to a worker. Returns without doing the work.

        A "replace" job carries either a pattern or a plain-English prompt. A prompt is turned
        into a pattern by the worker, not here: that is a call to a language model, and no
        request waits on one. The other kinds always need the language model.
        """
        connection = self._connections.get(token)
        if source_job_id:
            # A follow-up reads what an earlier job wrote, so it inherits that job's file.
            source = self._owned(token, source_job_id)
            if source.status is not JobStatus.SUCCESS:
                raise SourceJobUnusable("it did not finish successfully.")
            if not source.rows_total:
                raise SourceJobUnusable("it produced no rows.")
            if self._results.read_rows(source.id, 0, 1) is None:
                raise ResultsExpired()
            file_key, file_format = source.file_key, source.file_format
        else:
            file_format = FileFormat.from_key(file_key)
            if file_format is None:
                raise UnsupportedFile()
        if needs_model(kind, prompt):
            if not self._patterns.can_write:
                raise LLMNotConfigured()
        else:
            try:
                re.compile(pattern)
            except re.error as error:
                raise InvalidPattern(str(error)) from error
        if self._jobs.count_active(connection.id) >= self._max_active_jobs:
            raise TooManyActiveJobs()
        if not source_job_id:
            # Before a worker, a Spark application or any disk is committed to it. The size comes
            # from S3, not from the browser, so it is the one number the submitter cannot choose.
            # A follow-up is not sized: it never reads this file, only what an earlier job wrote
            # from it, and that job was sized when it was submitted.
            size = self._storage.file_size(connection, file_key)
            if size > self._max_file_bytes:
                raise FileTooLarge.over_limit(size, self._max_file_bytes)

        job = Job(
            id=str(uuid.uuid4()),
            connection_id=connection.id,
            file_key=file_key,
            file_format=file_format,
            pattern=pattern,
            replacement=replacement,
            columns=columns,
            created_at=self._now(),
            kind=kind,
            source_job_id=source_job_id or None,
            prompt=prompt or None,
            pattern_source="llm" if prompt and kind == "replace" else "user",
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
        progress = self._progress_writer(job)
        try:
            connection = self._connections.get_by_id(job.connection_id)
            if job.kind == "replace" and not self._settle_pattern(job):
                return  # the job changed hands while its pattern was being written
            # A follow-up reads Parquet that is already local; only a fresh Excel file has to
            # be downloaded and converted, and that takes a noticeable part of the job.
            source = self._source_of(job)
            excel = job.file_format is FileFormat.EXCEL and source is None
            opened_at = 0.3 if excel else 0.05
            with self._engine.open(
                job,
                connection,
                _span(progress, 0.0, opened_at),
                self._cancel_checker(job.id),
                source=source,
            ) as opened:
                plan = self._plan(job, opened, progress, opened_at)
                if plan is None:
                    return  # the job changed hands while its plan was being made
                operations, starts_at = plan
                result = opened.rewrite(
                    operations, self._results.path_for(job.id), _span(progress, starts_at, 1.0)
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
            if job.report is not None:
                # What each operation changed, beside what was planned.
                for described, rows in zip(
                    job.report.get("operations", []), result.changed_by_operation, strict=False
                ):
                    described["rows_changed"] = rows
            changed = self._change(
                job, lambda: job.succeed(self._now(), result.rows_total, result.rows_changed)
            )
            if not changed:  # it was marked failed or cancelled while the engine finished
                self._results.delete(job.id)

    def _settle_pattern(self, job: Job) -> bool:
        """Before any data is read: write the pattern if the job came with a prompt, and refuse
        one that could run for ever. False if the job was taken away in the meantime."""
        if job.needs_pattern:
            self._report(job, "Writing the pattern")
            suggestion, from_cache = self._patterns.suggest(job.prompt)
            # Persisted at once, so a retry or a takeover reuses it and the page can show it.
            return self._change(job, lambda: job.adopt(suggestion, from_cache))
        if job.pattern_source == "user":
            self._report(job, "Checking the pattern")
            self._patterns.check(job.pattern)  # a written pattern was checked when it was adopted
        return True

    def _plan(
        self, job: Job, opened: OpenFile, progress: Progress, opened_at: float
    ) -> tuple[list[Operation], float] | None:
        """The operations for this kind of job, and where on the progress bar rewriting starts.
        None if the job was taken away while a language model was being asked."""
        if job.kind == "replace":
            return [job.as_replace()], opened_at

        if job.kind == "redact_pii":
            progress(opened_at, "Looking for personal data")
            operations, report = self._pii.plan(
                opened.columns, opened.sample(SAMPLE_ROWS), job.columns
            )
            rewrite_at = opened_at + 0.05
        else:
            (column,) = job.columns
            # Two more than the limit: one may be the blank, and one tells "too many" from "all".
            counts = opened.distinct_values(column, MAX_VALUES + 2, _span(progress, opened_at, 0.4))
            progress(0.4, "Standardising the values")
            operations, report = self._standardiser.plan(column, counts, job.prompt)
            rewrite_at = 0.45

        # Saved before the rewrite starts, so the page can show it while Spark works.
        def adopt() -> None:
            job.report = report

        return (operations, rewrite_at) if self._change(job, adopt) else None

    def _report(self, job: Job, stage: str) -> None:
        job.stage = stage
        self._jobs.save_progress(job.id, job.progress, stage)

    def fail_unexpected(self, job_id: str, code: str, message: str) -> None:
        """For the task layer: an attempt ended in a way no use-case anticipated."""
        job = self._jobs.get(job_id)
        if job is not None and job.is_active:
            self._results.delete(job.id)
            self._fail(job, code, message)

    # --- helpers --------------------------------------------------------------------------

    def _source_of(self, job: Job) -> Path | None:
        """Where a follow-up reads from: the folder an earlier job wrote."""
        if not job.source_job_id:
            return None
        source = self._results.path_for(job.source_job_id)
        if self._results.read_rows(job.source_job_id, 0, 1) is None:
            raise ResultsExpired()
        return source

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


def _span(progress: Progress, start: float, end: float) -> Progress:
    """A part of the job reports its own progress from 0 to 1; this places it on the whole."""
    return lambda fraction, stage: progress(start + (end - start) * fraction, stage)
