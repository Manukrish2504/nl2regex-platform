"""The task layer, run for real: Celery task, service, engine, fake S3, Parquet and database."""

from unittest.mock import patch

import pytest
from celery.exceptions import Retry, SoftTimeLimitExceeded

from config.container import connection_service, job_service, preview_service
from domain import errors
from domain.connections import S3Credentials
from domain.jobs import JobStatus
from infrastructure.celery_queue import CeleryTaskQueue
from tasks.files import build_preview
from tasks.jobs import run_job

pytestmark = pytest.mark.django_db
CSV = b"id,email\n1,a@x.com\n2,\n3,c@z.org\n"


@pytest.fixture
def token(s3_bucket):
    token, _ = connection_service().connect(
        S3Credentials("AKIAEXAMPLEEXAMPLE00", "not-a-real-secret-key"), s3_bucket
    )
    return token


@pytest.fixture
def submit(token, put_object):
    """Submit a job for a small CSV without sending anything to a broker."""

    def submit_job(**overrides):
        request = {
            "file_key": put_object("data.csv", CSV),
            "pattern": r"\S+@\S+",
            "replacement": "REDACTED",
            "columns": ["email"],
        } | overrides
        with patch.object(CeleryTaskQueue, "enqueue_job"):
            return job_service().submit(token, **request)

    return submit_job


def test_a_job_runs_end_to_end(submit, token):
    job = submit()
    run_job.apply(args=[job.id])

    done = job_service().get(token, job.id)
    assert (done.status, done.progress, done.rows_total, done.rows_changed) == (
        JobStatus.SUCCESS,
        100,
        3,
        2,
    )
    page = job_service().read_page(token, job.id, page=1, page_size=50)
    assert page.rows == [["1", "REDACTED"], ["2", None], ["3", "REDACTED"]]


def test_a_permanent_failure_fails_the_job_and_is_not_retried(submit, token):
    job = submit(columns=["no_such_column"])
    result = run_job.apply(args=[job.id])

    assert result.successful()  # the task itself ended normally: no retry was asked for
    failed = job_service().get(token, job.id)
    assert (failed.status, failed.error_code) == (JobStatus.FAILED, "column_not_found")


def test_a_transient_failure_asks_celery_to_retry(submit, token):
    job = submit()
    engine = job_service()._engine
    with patch.object(engine, "open", side_effect=errors.StorageUnreachable()):
        with pytest.raises(Retry):
            run_job.apply(args=[job.id], throw=True)

    waiting = job_service().get(token, job.id)
    assert (waiting.status, waiting.attempts) == (JobStatus.QUEUED, 1)


def test_the_soft_time_limit_fails_the_job_cleanly(submit, token):
    job = submit()
    with patch.object(job_service()._engine, "open", side_effect=SoftTimeLimitExceeded()):
        run_job.apply(args=[job.id])

    failed = job_service().get(token, job.id)
    assert (failed.status, failed.error_code) == (JobStatus.FAILED, "timed_out")


def test_a_crash_in_our_own_code_fails_the_job_without_leaking_details(submit, token):
    job = submit()
    with patch.object(job_service()._engine, "open", side_effect=RuntimeError("secret internals")):
        run_job.apply(args=[job.id])

    failed = job_service().get(token, job.id)
    assert (failed.status, failed.error_code) == (JobStatus.FAILED, "internal_error")
    assert "secret internals" not in failed.error_message


def test_a_redelivered_message_takes_over_a_running_job(submit, token):
    job = submit()
    with patch.object(job_service()._engine, "open", side_effect=SystemExit):  # the worker dies
        with pytest.raises(SystemExit):
            run_job.apply(args=[job.id], throw=True)
    assert job_service().get(token, job.id).status is JobStatus.RUNNING

    run_job.apply(args=[job.id])  # a plain duplicate does nothing
    assert job_service().get(token, job.id).status is JobStatus.RUNNING

    # What a worker sees when the broker hands the message out again because its first delivery
    # was never acknowledged. (.apply() builds its own delivery_info, so the request is pushed.)
    run_job.push_request(delivery_info={"redelivered": True})
    try:
        run_job.run(job.id)
    finally:
        run_job.pop_request()
    done = job_service().get(token, job.id)
    assert (done.status, done.attempts) == (JobStatus.SUCCESS, 2)


def test_tasks_are_enqueued_by_name_with_ids_only(submit):
    with patch("infrastructure.celery_queue.current_app.send_task") as send_task:
        job = job_service().submit.__self__._queue.enqueue_job("some-job-id")
    send_task.assert_called_once_with("tasks.jobs.run_job", args=["some-job-id"])
    assert job is None
    assert run_job.name == "tasks.jobs.run_job"  # the name the queue uses must be the task's name
    assert build_preview.name == "tasks.files.build_preview"


def test_the_preview_task_builds_a_preview(token, put_object):
    key = put_object("data.csv", CSV)
    with patch.object(CeleryTaskQueue, "enqueue_preview") as enqueue:
        assert preview_service().get(token, key) == {"status": "pending"}
    connection_id = enqueue.call_args.args[0]

    build_preview.apply(args=[connection_id, key])
    assert preview_service().get(token, key) == {
        "status": "done",
        "columns": ["id", "email"],
        "rows": [["1", "a@x.com"], ["2", None], ["3", "c@z.org"]],
    }


def test_jobs_have_their_own_queue_and_previews_do_not_wait_behind_them():
    from config import celery_app

    route = celery_app.amqp.router.route
    assert route({}, "tasks.jobs.run_job")["queue"].name == "jobs"
    assert route({}, "tasks.files.build_preview")["queue"].name == "celery"
