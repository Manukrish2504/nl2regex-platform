from datetime import UTC, datetime, timedelta

import pytest
from fakes import (
    FakeAdviceCache,
    FakeClassifier,
    FakeEngine,
    FakeJobs,
    FakePatternCache,
    FakeProbe,
    FakeQueue,
    FakeResults,
    FakeStandardiser,
    FakeStorage,
    FakeVault,
    FakeWriter,
)

from domain import errors
from domain.advice import Finding
from domain.connections import S3Credentials
from domain.jobs import JobCancelled, JobStatus, RetryLater, TransformResult
from domain.operations import MapValues, MaskCells
from domain.patterns import PatternSuggestion
from services.connections import ConnectionService
from services.jobs import JobService
from services.patterns import PatternService
from services.pii import PiiService
from services.standardise import StandardiseService

CREDENTIALS = S3Credentials("AKIAEXAMPLEEXAMPLE00", "not-a-real-secret-key")
START = datetime(2026, 9, 20, 12, 0, tzinfo=UTC)


class World:
    """One service wired to fakes, plus a connected browser token."""

    def __init__(
        self,
        engine=None,
        results=None,
        writer=None,
        probe=None,
        classifier=None,
        standardiser=None,
        file_size=1_000,
        max_file_bytes=5 * 1000**3,
    ):
        self.clock = START
        self.vault = FakeVault()
        self.storage = FakeStorage(size=file_size)
        self.connections = ConnectionService(self.storage, self.vault)
        self.jobs, self.queue = FakeJobs(), FakeQueue()
        self.engine, self.results = engine or FakeEngine(), results or FakeResults()
        self.writer, self.probe = writer or FakeWriter(), probe or FakeProbe()
        self.classifier = classifier or FakeClassifier()
        self.standardiser = standardiser or FakeStandardiser()
        patterns = PatternService(self.writer, FakePatternCache(), self.probe)
        self.service = JobService(
            self.connections,
            self.jobs,
            self.queue,
            self.storage,
            self.engine,
            self.results,
            patterns,
            PiiService(self.classifier, FakeAdviceCache(), patterns),
            StandardiseService(self.standardiser, FakeAdviceCache()),
            max_active_jobs=3,
            max_attempts=3,
            max_file_bytes=max_file_bytes,
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

    # The engine said "half way through rewriting". Opening the file is the first 5% of the
    # job, so half of the rest puts the job at 52%.
    assert (seen[0].status, seen[0].progress, seen[0].stage) == (
        JobStatus.RUNNING,
        52,
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
    assert cancelled.progress == 52  # how far it got, not reset to zero
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


# --- a job that comes as a prompt --------------------------------------------------------------

EMAILS = PatternSuggestion(
    pattern=r"\S+@\S+",
    explanation="Matches e-mail addresses such as a@x.com.",
    replacement="REDACTED",
    columns=["Email"],
    should_match=["write to a@x.com"],
    should_not_match=["no address here"],
)
REQUEST = {"pattern": "", "prompt": "find email addresses", "replacement": "", "columns": []}


def test_a_prompt_is_queued_without_calling_the_language_model():
    world = World(writer=FakeWriter(EMAILS))
    job = world.submit(**REQUEST)

    assert (job.prompt, job.pattern, job.pattern_source) == ("find email addresses", "", "llm")
    assert world.writer.calls == []  # that call belongs to the worker, not to the request


def test_the_worker_writes_the_pattern_and_the_engine_runs_with_it():
    world = World(writer=FakeWriter(EMAILS))
    job = world.submit(**REQUEST)
    seen = {}
    world.engine.during = lambda running, _cancel: seen.update(pattern=running.pattern)
    world.service.run(job.id)

    done = world.jobs.get(job.id)
    assert seen["pattern"] == EMAILS.pattern
    assert (done.status, done.pattern, done.pattern_source) == (
        JobStatus.SUCCESS,
        EMAILS.pattern,
        "llm",
    )
    assert done.explanation == EMAILS.explanation
    # The request stated a replacement and a column, and the user had filled in neither.
    assert (done.replacement, done.columns) == ("REDACTED", ["Email"])


def test_what_the_user_filled_in_beats_what_the_request_says():
    world = World(writer=FakeWriter(EMAILS))
    job = world.submit(**REQUEST | {"replacement": "***", "columns": ["notes"]})
    world.service.run(job.id)

    done = world.jobs.get(job.id)
    assert (done.replacement, done.columns) == ("***", ["notes"])


def test_a_retry_reuses_the_pattern_already_written():
    world = World(engine=FakeEngine(error=errors.StorageUnreachable()), writer=FakeWriter(EMAILS))
    job = world.submit(**REQUEST)
    for _ in range(2):
        with pytest.raises(RetryLater):
            world.service.run(job.id)

    assert len(world.writer.calls) == 1  # the second attempt found the pattern on the job


def test_an_unreachable_language_model_takes_the_retry_path():
    world = World(writer=FakeWriter(errors.LLMUnavailable()))
    job = world.submit(**REQUEST)
    with pytest.raises(RetryLater):
        world.service.run(job.id)

    waiting = world.jobs.get(job.id)
    assert waiting.status is JobStatus.QUEUED
    assert "language model could not be reached" in waiting.stage
    assert world.engine.runs == 0


def test_a_request_that_is_not_about_a_pattern_fails_the_job_with_the_reason():
    refusal = errors.PatternNotUnderstood("It asks about the weather.")
    world = World(writer=FakeWriter(refusal))
    job = world.submit(**REQUEST | {"prompt": "what is the weather today"})
    world.service.run(job.id)

    failed = world.jobs.get(job.id)
    assert (failed.status, failed.error_code) == (JobStatus.FAILED, "pattern_not_understood")
    assert "It asks about the weather." in failed.error_message
    assert world.engine.runs == 0


def test_a_typed_pattern_that_could_hang_is_refused_before_any_data_is_read():
    world = World(probe=FakeProbe(unsafe=[r"(a+)+$"]))
    job = world.submit(pattern=r"(a+)+$")
    world.service.run(job.id)

    failed = world.jobs.get(job.id)
    assert (failed.status, failed.error_code) == (JobStatus.FAILED, "unsafe_pattern")
    assert world.engine.runs == 0


def test_a_prompt_is_refused_at_once_when_no_language_model_is_configured():
    writer = FakeWriter()
    writer.is_configured = False
    world = World(writer=writer)
    with pytest.raises(errors.LLMNotConfigured):
        world.submit(**REQUEST)
    assert world.queue.jobs == []


# --- the two transformations a language model plans -------------------------------------------

PEOPLE = [["1", "John Doe", "USA"], ["2", "Jane Smith", "us"]]


def test_redacting_personal_data_plans_from_a_sample_and_reports_what_it_did():
    engine = FakeEngine(
        columns=["id", "name", "country"],
        rows=PEOPLE,
        result=TransformResult(rows_total=2, rows_changed=2, changed_by_operation=[2]),
    )
    world = World(engine=engine, classifier=FakeClassifier([Finding("name", "name", "names")]))
    job = world.submit(kind="redact_pii", pattern="", replacement="", columns=[])
    seen = {}
    engine.during = lambda running, _cancel: seen.update(report=world.jobs.get(running.id).report)
    world.service.run(job.id)

    assert engine.operations == [MaskCells("[NAME]", ["name"])]
    # The model saw shapes of the sampled rows, not the rows.
    assert world.classifier.calls[0][1].shapes == ["Aaaa Aaa"]
    assert seen["report"]["findings"][0]["column"] == "name"  # on the page while Spark works
    done = world.jobs.get(job.id)
    assert done.status is JobStatus.SUCCESS
    assert done.report["operations"] == [
        {"kind": "name", "placeholder": "[NAME]", "columns": ["name"], "rows_changed": 2}
    ]


def test_standardising_counts_the_values_first_and_then_maps_them():
    engine = FakeEngine(
        columns=["id", "name", "country"],
        counts=[("USA", 40), ("us", 30), (None, 5)],
        result=TransformResult(rows_total=75, rows_changed=30, changed_by_operation=[30]),
    )
    world = World(engine=engine, standardiser=FakeStandardiser([("us", "USA")]))
    job = world.submit(
        kind="standardise", pattern="", replacement="", columns=["country"], prompt="prefer USA"
    )
    world.service.run(job.id)

    assert world.standardiser.calls == [("country", ["USA", "us"], "prefer USA")]
    assert engine.operations == [MapValues("country", {"us": "USA"})]
    done = world.jobs.get(job.id)
    assert (done.status, done.rows_changed) == (JobStatus.SUCCESS, 30)
    assert done.report["mapping"] == [{"from": "us", "to": "USA", "rows": 30}]


def test_a_column_with_too_many_values_fails_the_job_before_the_model_is_asked():
    engine = FakeEngine(columns=["email"], counts=[(f"user{n}@x.com", 1) for n in range(400)])
    world = World(engine=engine)
    job = world.submit(kind="standardise", pattern="", replacement="", columns=["email"])
    world.service.run(job.id)

    failed = world.jobs.get(job.id)
    assert (failed.status, failed.error_code) == (JobStatus.FAILED, "not_categorical")
    assert world.standardiser.calls == [] and engine.runs == 0


def test_nothing_to_redact_ends_the_job_with_a_plain_message():
    world = World(engine=FakeEngine(rows=[["1", "a@x.com"]]), classifier=FakeClassifier([]))
    job = world.submit(kind="redact_pii", pattern="", replacement="", columns=[])
    world.service.run(job.id)

    failed = world.jobs.get(job.id)
    assert failed.error_code == "nothing_to_change"
    assert "No personal data was found" in failed.error_message


def test_these_kinds_need_a_language_model():
    writer = FakeWriter()
    writer.is_configured = False
    world = World(writer=writer)
    for kind, columns in (("redact_pii", []), ("standardise", ["country"])):
        with pytest.raises(errors.LLMNotConfigured):
            world.submit(kind=kind, pattern="", replacement="", columns=columns)


# --- follow-ups ------------------------------------------------------------------------------


def test_a_follow_up_reads_the_earlier_jobs_result_and_inherits_its_file():
    world = World(results=FakeResults(rows=[["1", "[EMAIL]"]]))
    first = world.submit()
    world.service.run(first.id)

    second = world.service.submit(
        world.token, replacement="***", columns=[], pattern=r"\d+", source_job_id=first.id
    )
    world.service.run(second.id)

    assert second.file_key == first.file_key
    assert second.source_job_id == first.id
    # The engine was pointed at the first job's output, not at the bucket.
    assert world.engine.source == world.results.path_for(first.id)
    assert world.jobs.get(second.id).status is JobStatus.SUCCESS


def test_only_a_job_that_finished_can_be_followed_up():
    world = World(engine=FakeEngine(error=errors.ColumnNotFound(["emial"])))
    failed = world.submit()
    world.service.run(failed.id)

    with pytest.raises(errors.SourceJobUnusable, match="did not finish successfully"):
        world.service.submit(
            world.token, replacement="", columns=[], pattern="a", source_job_id=failed.id
        )
    assert len(world.queue.jobs) == 1  # the failed job only


def test_a_follow_up_is_not_measured_against_the_file_in_the_bucket():
    """It never reads that file, only what an earlier job wrote from it, and that job was
    measured when it was submitted. Sizing it again would refuse work already paid for, and
    would fail outright once the original file is deleted."""
    world = World(results=FakeResults(rows=[["1", "x"]]), file_size=100, max_file_bytes=1_000)
    first = world.submit()
    world.service.run(first.id)
    world.storage.size = 10_000_000  # the bucket file grew, or a smaller limit was set

    second = world.service.submit(
        world.token, replacement="", columns=[], pattern="a", source_job_id=first.id
    )

    assert second.source_job_id == first.id
    # And the same request without a source is refused, so the limit itself still works.
    with pytest.raises(errors.FileTooLarge):
        world.submit()


def test_a_follow_up_needs_the_earlier_result_to_still_be_there():
    world = World(results=FakeResults(rows=[["1", "x"]]))
    first = world.submit()
    world.service.run(first.id)
    world.results.rows = None  # the eight-hour clean-up has taken it

    with pytest.raises(errors.ResultsExpired):
        world.service.submit(
            world.token, replacement="", columns=[], pattern="a", source_job_id=first.id
        )


def test_another_connections_job_cannot_be_followed_up():
    world = World(results=FakeResults(rows=[["1", "x"]]))
    first = world.submit()
    world.service.run(first.id)
    other_token, _ = world.connections.connect(CREDENTIALS, "another-bucket")

    with pytest.raises(errors.JobNotFound):
        world.service.submit(
            other_token, replacement="", columns=[], pattern="a", source_job_id=first.id
        )
