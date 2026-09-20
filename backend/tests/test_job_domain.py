from datetime import UTC, datetime, timedelta

import pytest

from domain.connections import FileFormat
from domain.errors import InvalidTransition
from domain.jobs import Job, JobStatus

NOW = datetime(2026, 9, 20, 12, 0, tzinfo=UTC)


def make_job(status=JobStatus.QUEUED, **fields):
    return Job(
        id="job-1",
        connection_id="c" * 64,
        file_key="samples/customers.csv",
        file_format=FileFormat.CSV,
        pattern=r"\d+",
        replacement="#",
        columns=[],
        created_at=NOW,
        status=status,
        **fields,
    )


MOVES = {
    "start": lambda job: job.start(NOW),
    "succeed": lambda job: job.succeed(NOW, rows_total=10, rows_changed=3),
    "fail": lambda job: job.fail(NOW, "some_code", "Some message."),
    "cancel": lambda job: job.cancel(NOW),
    "requeue_for_retry": lambda job: job.requeue_for_retry("S3 was unreachable"),
}

ALLOWED = {
    # start from RUNNING is the takeover after a worker died mid-job.
    "start": {JobStatus.QUEUED, JobStatus.RUNNING},
    "succeed": {JobStatus.RUNNING},
    "fail": {JobStatus.QUEUED, JobStatus.RUNNING},
    "cancel": {JobStatus.QUEUED, JobStatus.RUNNING},
    "requeue_for_retry": {JobStatus.RUNNING},
}


@pytest.mark.parametrize("move", MOVES)
@pytest.mark.parametrize("status", JobStatus)
def test_every_status_change_is_either_allowed_or_refused(move, status):
    job = make_job(status)
    if status in ALLOWED[move]:
        MOVES[move](job)
    else:
        with pytest.raises(InvalidTransition):
            MOVES[move](job)
        assert job.status is status  # a refused move changes nothing


def test_finished_jobs_never_change_again():
    for status in (JobStatus.SUCCESS, JobStatus.FAILED, JobStatus.CANCELLED):
        for move in MOVES.values():
            with pytest.raises(InvalidTransition):
                move(make_job(status))


def test_start_counts_the_attempt_and_resets_progress():
    job = make_job(JobStatus.RUNNING, attempts=1, progress=60)
    job.start(NOW)
    assert (job.attempts, job.progress, job.started_at) == (2, 0, NOW)


def test_success_records_the_outcome():
    job = make_job(JobStatus.RUNNING)
    job.succeed(NOW, rows_total=10, rows_changed=3)
    assert (job.status, job.progress, job.rows_total, job.rows_changed, job.finished_at) == (
        JobStatus.SUCCESS,
        100,
        10,
        3,
        NOW,
    )


def test_retry_goes_back_to_the_queue_and_says_why():
    job = make_job(JobStatus.RUNNING, progress=40)
    job.requeue_for_retry("Could not reach Amazon S3.")
    assert job.status is JobStatus.QUEUED
    assert job.progress == 0
    assert "Could not reach Amazon S3." in job.stage


def test_only_a_job_running_past_the_limit_is_stale():
    limit = timedelta(minutes=17)
    running = make_job(JobStatus.RUNNING, started_at=NOW)
    assert not running.is_stale(NOW + timedelta(minutes=16), limit)
    assert running.is_stale(NOW + timedelta(minutes=18), limit)
    assert not make_job(JobStatus.QUEUED).is_stale(NOW + timedelta(days=1), limit)
    assert not make_job(JobStatus.SUCCESS, started_at=NOW).is_stale(NOW + timedelta(days=1), limit)
