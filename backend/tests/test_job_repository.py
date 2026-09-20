from datetime import UTC, datetime

import pytest

from domain.connections import FileFormat
from domain.jobs import Job, JobStatus
from infrastructure.job_repository import DjangoJobRepository

pytestmark = pytest.mark.django_db
NOW = datetime(2026, 9, 20, 12, 0, tzinfo=UTC)


def new_job(job_id="11111111-1111-4111-8111-111111111111", connection_id="c" * 64, **fields):
    return Job(
        id=job_id,
        connection_id=connection_id,
        file_key="samples/customers.csv",
        file_format=FileFormat.CSV,
        pattern=r"\S+@\S+",
        replacement="REDACTED",
        columns=["email", "notes"],
        created_at=NOW,
        **fields,
    )


def test_round_trip_keeps_every_field():
    repository = DjangoJobRepository()
    repository.add(new_job())
    assert repository.get(new_job().id) == new_job()
    assert repository.get("22222222-2222-4222-8222-222222222222") is None


def test_save_only_writes_when_status_and_attempts_still_match():
    repository = DjangoJobRepository()
    job = new_job()
    repository.add(job)

    first, second = repository.get(job.id), repository.get(job.id)  # two workers, same message
    first.start(NOW)
    second.start(NOW)
    assert repository.save(first, JobStatus.QUEUED, 0) is True
    assert repository.save(second, JobStatus.QUEUED, 0) is False  # the loser changes nothing

    stored = repository.get(job.id)
    assert (stored.status, stored.attempts) == (JobStatus.RUNNING, 1)


def test_two_takeovers_of_a_dead_workers_job_cannot_both_win():
    repository = DjangoJobRepository()
    job = new_job(status=JobStatus.RUNNING, attempts=1)
    repository.add(job)

    first, second = repository.get(job.id), repository.get(job.id)
    first.start(NOW)
    second.start(NOW)
    # The status is RUNNING before and after, so only the attempt count can tell them apart.
    assert repository.save(first, JobStatus.RUNNING, 1) is True
    assert repository.save(second, JobStatus.RUNNING, 1) is False


def test_cancel_requests_survive_every_other_write():
    repository = DjangoJobRepository()
    job = new_job()
    repository.add(job)
    assert repository.request_cancel(job.id) is False  # only a running job can be flagged

    job.start(NOW)
    repository.save(job, JobStatus.QUEUED, 0)
    worker_copy = repository.get(job.id)  # read before the cancel request arrives
    assert repository.request_cancel(job.id) is True

    repository.save_progress(job.id, 40, "Transforming")
    worker_copy.succeed(NOW, rows_total=5, rows_changed=1)
    repository.save(worker_copy, JobStatus.RUNNING, 1)  # a stale copy with cancel_requested False

    assert repository.is_cancel_requested(job.id) is True


def test_progress_is_only_written_to_a_running_job():
    repository = DjangoJobRepository()
    job = new_job()
    repository.add(job)
    repository.save_progress(job.id, 40, "Transforming")
    assert repository.get(job.id).progress == 0

    job.start(NOW)
    repository.save(job, JobStatus.QUEUED, 0)
    repository.save_progress(job.id, 40, "Transforming")
    assert (repository.get(job.id).progress, repository.get(job.id).stage) == (40, "Transforming")


def test_listing_is_per_connection_newest_first_and_counts_active_jobs():
    repository = DjangoJobRepository()
    for index, status in enumerate([JobStatus.SUCCESS, JobStatus.QUEUED, JobStatus.RUNNING]):
        job = new_job(job_id=f"0000000{index}-0000-4000-8000-000000000000", status=status)
        job.created_at = NOW.replace(minute=index)
        repository.add(job)
    repository.add(new_job(job_id="99999999-0000-4000-8000-000000000000", connection_id="d" * 64))

    listed = repository.list_for_connection("c" * 64, limit=2)
    assert [job.status for job in listed] == [JobStatus.RUNNING, JobStatus.QUEUED]
    assert repository.count_active("c" * 64) == 2
    assert repository.count_active("d" * 64) == 1
