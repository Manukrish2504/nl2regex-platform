from datetime import UTC, datetime, timedelta

import pytest
from fakes import FakeEngine, FakeJobs, FakeQueue, FakeResults, FakeStorage, FakeVault

from domain import errors
from domain.connections import S3Credentials
from domain.jobs import JobCancelled, JobStatus, RetryLater, TransformResult
from services.connections import ConnectionService
from services.jobs import JobService

CREDENTIALS = S3Credentials("AKIAEXAMPLEEXAMPLE00", "not-a-real-secret-key")
START = datetime(2026, 9, 20, 12, 0, tzinfo=UTC)


class World:
    """One service wired to fakes, plus a connected browser token."""

    def __init__(self, engine=None, results=None):
        self.clock = START
        self.vault = FakeVault()
        self.connections = ConnectionService(FakeStorage(), self.vault)
        self.jobs, self.queue = FakeJobs(), FakeQueue()
        self.engine, self.results = engine or FakeEngine(), results or FakeResults()
        self.service = JobService(
            self.connections,
            self.jobs,
            self.queue,
            self.engine,
            self.results,
            max_active_jobs=3,
            max_attempts=3,
            stale_after=timedelta(minutes=17),
            results_max_age=timedelta(hours=8),
            clock=lambda: self.clock,
        )
        self.token, self.connection = self.connections.connect(CREDENTIALS, "my-bucket")

    def submit(self, **overrides):
        request = {
            "file_key": "samples/customers.csv",
            "pattern": r"\S+@\S+",
            "replacement": "REDACTED",
            "columns": ["email"],
        } | overrides
        return self.service.submit(self.token, **request)


# --- submit --------------------------------------------------------------------------------


def test_submit_persists_and_enqueues_without_running_anything():
    world = World()
    job = world.submit()

    assert job.status is JobStatus.QUEUED
    assert world.queue.jobs == [job.id]
    assert world.engine.runs == 0
    assert world.jobs.get(job.id).connection_id == world.connection.id


def test_submit_needs_a_live_connection():
    with pytest.raises(errors.ConnectionNotFound):
        World().service.submit("unknown-token", "a.csv", "x", "y", [])


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({"file_key": "notes.txt"}, errors.UnsupportedFile),
        ({"pattern": "(unclosed"}, errors.InvalidPattern),
    ],
)
def test_submit_rejects_bad_requests_before_queueing(overrides, expected):
    world = World()
    with pytest.raises(expected):
        world.submit(**overrides)
    assert world.queue.jobs == []


def test_active_jobs_are_capped_per_connection():
    world = World()
    for _ in range(3):
        world.submit()
    with pytest.raises(errors.TooManyActiveJobs):
        world.submit()

    # A finished job frees a slot.
    world.service.run(world.queue.jobs[0])
    world.submit()


# --- ownership -----------------------------------------------------------------------------


def test_another_connections_job_looks_like_a_missing_one():
    world = World()
    job = world.submit()
    other_token, _ = world.connections.connect(CREDENTIALS, "another-bucket")

    for call in (world.service.get, world.service.cancel):
        with pytest.raises(errors.JobNotFound):
            call(other_token, job.id)
    with pytest.raises(errors.JobNotFound):
        world.service.read_page(other_token, job.id, 1, 50)
    assert world.service.recent(other_token) == []
    assert [mine.id for mine in world.service.recent(world.token)] == [job.id]


# --- run -----------------------------------------------------------------------------------


def test_run_succeeds_and_records_the_outcome():
    world = World(engine=FakeEngine(result=TransformResult(rows_total=100, rows_changed=42)))
    job = world.submit()
    world.service.run(job.id)

    done = world.jobs.get(job.id)
    assert (done.status, done.progress, done.rows_total, done.rows_changed, done.attempts) == (
        JobStatus.SUCCESS,
        100,
        100,
        42,
        1,
    )


def test_progress_is_persisted_while_running():
    seen = []
    world = World()
    world.engine.during = lambda job, _cancel: seen.append(world.jobs.get(job.id))
    world.service.run(world.submit().id)

    assert (seen[0].status, seen[0].progress, seen[0].stage) == (
        JobStatus.RUNNING,
        50,
        "Transforming",
    )


def test_a_permanent_failure_fails_the_job_with_the_users_message():
    world = World(engine=FakeEngine(error=errors.ColumnNotFound(["emial"])))
    job = world.submit()
    world.service.run(job.id)

    failed = world.jobs.get(job.id)
    assert failed.status is JobStatus.FAILED
    assert (failed.error_code, failed.error_message) == (
        "column_not_found",
        "The file has no column named 'emial'.",
    )
    assert job.id in world.results.deleted  # no partial output is left behind


def test_an_expired_connection_fails_the_job_with_a_reconnect_message():
    world = World()
    job = world.submit()
    world.vault.entries.clear()
    world.service.run(job.id)

    assert world.jobs.get(job.id).error_code == "connection_not_found"
    assert world.engine.runs == 0


@pytest.mark.parametrize("error", [errors.StorageUnreachable(), errors.EngineUnavailable()])
def test_a_transient_failure_requeues_and_asks_for_a_retry(error):
    world = World(engine=FakeEngine(error=error))
    job = world.submit()
    with pytest.raises(RetryLater):
        world.service.run(job.id)

    waiting = world.jobs.get(job.id)
    assert (waiting.status, waiting.attempts) == (JobStatus.QUEUED, 1)
    assert error.message in waiting.stage


def test_transient_failures_give_up_after_the_attempt_cap():
    world = World(engine=FakeEngine(error=errors.StorageUnreachable()))
    job = world.submit()
    for _ in range(2):
        with pytest.raises(RetryLater):
            world.service.run(job.id)
    world.service.run(job.id)  # the third attempt fails for good, without asking again

    failed = world.jobs.get(job.id)
    assert (failed.status, failed.attempts, failed.error_code) == (
        JobStatus.FAILED,
        3,
        "storage_unreachable",
    )
    assert "Gave up after 3 tries" in failed.error_message


def test_a_first_delivery_never_touches_a_job_that_is_already_running():
    world = World()
    job = world.submit()
    world.engine.during = lambda job, _cancel: world.service.run(job.id)  # a duplicate delivery
    world.service.run(job.id)

    assert world.engine.runs == 1
    assert world.jobs.get(job.id).status is JobStatus.SUCCESS


def test_a_redelivered_message_takes_over_a_job_whose_worker_died():
    world = World()
    job = world.submit()
    crashed = world.jobs.get(job.id)
    crashed.start(START)  # a worker started it, then died without a trace
    world.jobs.save(crashed, JobStatus.QUEUED, 0)

    world.service.run(job.id)  # not redelivered: treated as a duplicate
    assert world.engine.runs == 0

    world.service.run(job.id, redelivered=True)
    done = world.jobs.get(job.id)
    assert (done.status, done.attempts) == (JobStatus.SUCCESS, 2)


def test_a_job_that_keeps_killing_its_worker_is_stopped():
    world = World()
    job = world.submit()
    crashed = world.jobs.get(job.id)
    for attempt in range(3):
        crashed.start(START)
        world.jobs.save(crashed, crashed.status if attempt else JobStatus.QUEUED, attempt)

    world.service.run(job.id, redelivered=True)
    failed = world.jobs.get(job.id)
    assert (failed.status, failed.error_code) == (JobStatus.FAILED, "too_many_attempts")
    assert world.engine.runs == 0


def test_run_ignores_unknown_and_finished_jobs():
    world = World()
    world.service.run("no-such-job")
    job = world.submit()
    world.service.cancel(world.token, job.id)
    world.service.run(job.id)  # the queued task still fires; the database says it is cancelled
    assert world.engine.runs == 0


def test_an_unexpected_failure_reported_by_the_task_layer_fails_the_job():
    world = World()
    job = world.submit()
    world.service.fail_unexpected(job.id, "timed_out", "Too slow.")
    assert world.jobs.get(job.id).error_code == "timed_out"

    world.service.fail_unexpected(job.id, "internal_error", "Again.")  # already finished: no change
    assert world.jobs.get(job.id).error_code == "timed_out"


# --- cancel --------------------------------------------------------------------------------


def test_cancelling_a_queued_job_is_immediate():
    world = World()
    job = world.submit()
    assert world.service.cancel(world.token, job.id).status is JobStatus.CANCELLED


def test_cancelling_a_running_job_asks_the_engine_to_stop():
    world = World()
    job = world.submit()

    def cancel_mid_run(running, should_cancel):
        assert not should_cancel()
        flagged = world.service.cancel(world.token, running.id)
        assert (flagged.status, flagged.cancel_requested) == (JobStatus.RUNNING, True)
        raise JobCancelled()

    world.engine.during = cancel_mid_run
    world.service.run(job.id)

    cancelled = world.jobs.get(job.id)
    assert cancelled.status is JobStatus.CANCELLED
    assert cancelled.progress == 50  # how far it got, not reset to zero
    assert job.id in world.results.deleted


def test_a_workers_save_never_erases_a_cancel_request():
    world = World()
    job = world.submit()
    seen = {}

    def request_cancel_then_finish(running, _should_cancel):
        world.service.cancel(world.token, running.id)
        seen["flag"] = world.jobs.get(running.id).cancel_requested

    world.engine.during = request_cancel_then_finish
    world.service.run(job.id)  # the engine ignores the request and finishes anyway

    assert seen["flag"] is True
    assert world.jobs.get(job.id).cancel_requested is True


def test_cancelling_a_finished_job_changes_nothing():
    world = World()
    job = world.submit()
    world.service.run(job.id)
    assert world.service.cancel(world.token, job.id).status is JobStatus.SUCCESS


def test_success_loses_to_a_failure_recorded_meanwhile():
    world = World()
    job = world.submit()

    def fail_behind_the_engines_back(running, _should_cancel):
        world.service.fail_unexpected(running.id, "timed_out", "Marked stale.")

    world.engine.during = fail_behind_the_engines_back
    world.service.run(job.id)

    assert world.jobs.get(job.id).status is JobStatus.FAILED
    assert job.id in world.results.deleted  # output of a job that did not succeed is not kept


# --- the stale-job rule --------------------------------------------------------------------


def test_a_job_running_past_the_time_limit_is_failed_when_read():
    world = World()
    job = world.submit()
    started = world.jobs.get(job.id)
    started.start(START)
    world.jobs.save(started, JobStatus.QUEUED, 0)

    world.clock = START + timedelta(minutes=16)
    assert world.service.get(world.token, job.id).status is JobStatus.RUNNING

    world.clock = START + timedelta(minutes=18)
    stale = world.service.get(world.token, job.id)
    assert (stale.status, stale.error_code) == (JobStatus.FAILED, "timed_out")
    assert world.jobs.get(job.id).status is JobStatus.FAILED  # persisted, not just reported


# --- results -------------------------------------------------------------------------------


def test_pages_are_only_served_for_successful_jobs():
    world = World(results=FakeResults(rows=[[str(n), f"user{n}@x.com"] for n in range(120)]))
    job = world.submit()
    with pytest.raises(errors.JobNotFinished):
        world.service.read_page(world.token, job.id, 1, 50)

    world.engine.result = TransformResult(rows_total=120, rows_changed=120)
    world.service.run(job.id)
    page = world.service.read_page(world.token, job.id, page=3, page_size=50)
    assert (page.columns, len(page.rows), page.rows[0][0], page.total_rows) == (
        ["id", "email"],
        20,
        "100",
        120,
    )


def test_deleted_results_are_reported_as_expired():
    world = World(results=FakeResults(rows=None))
    job = world.submit()
    world.service.run(job.id)
    with pytest.raises(errors.ResultsExpired):
        world.service.read_page(world.token, job.id, 1, 50)


# --- disconnect ----------------------------------------------------------------------------


def test_forgetting_a_connection_stops_its_jobs_and_deletes_their_output():
    world = World()
    finished, queued = world.submit(), world.submit()
    world.service.run(finished.id)

    world.service.forget_jobs(world.token)
    assert world.jobs.get(queued.id).status is JobStatus.CANCELLED
    assert {finished.id, queued.id} <= set(world.results.deleted)

    world.service.forget_jobs("expired-token")  # nothing to do, and no error
