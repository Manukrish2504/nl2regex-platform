"""In-memory stand-ins for the ports, so services are tested without a database, S3 or Celery."""

import copy

from domain.connections import FileListing
from domain.jobs import ACTIVE_STATUSES, JobStatus, TransformResult


class FakeStorage:
    def __init__(self, error=None):
        self.error = error

    def resolve_bucket(self, credentials, bucket):
        if self.error:
            raise self.error
        return "eu-north-1"

    def list_files(self, connection, prefix, page_token):
        return FileListing([f"{connection.bucket}/{prefix}"], [], None)


class FakeVault:
    def __init__(self):
        self.entries = {}

    def store(self, connection):
        self.entries[connection.id] = connection

    def load(self, connection_id):
        return self.entries.get(connection_id)

    def delete(self, connection_id):
        self.entries.pop(connection_id, None)


class FakeJobs:
    """Keeps copies, like a database: changing a Job object does nothing until it is saved."""

    def __init__(self):
        self.rows = {}

    def add(self, job):
        self.rows[job.id] = copy.deepcopy(job)

    def get(self, job_id):
        return copy.deepcopy(self.rows.get(job_id))

    def save(self, job, expected_status, expected_attempts):
        stored = self.rows.get(job.id)
        if not stored or (stored.status, stored.attempts) != (expected_status, expected_attempts):
            return False
        cancel_requested = stored.cancel_requested  # never written by save()
        self.rows[job.id] = copy.deepcopy(job)
        self.rows[job.id].cancel_requested = cancel_requested
        return True

    def save_progress(self, job_id, progress, stage):
        stored = self.rows[job_id]
        if stored.status is JobStatus.RUNNING:
            stored.progress, stored.stage = progress, stage

    def request_cancel(self, job_id):
        stored = self.rows[job_id]
        if stored.status is not JobStatus.RUNNING:
            return False
        stored.cancel_requested = True
        return True

    def is_cancel_requested(self, job_id):
        return self.rows[job_id].cancel_requested

    def list_for_connection(self, connection_id, limit):
        mine = [job for job in self.rows.values() if job.connection_id == connection_id]
        return copy.deepcopy(sorted(mine, key=lambda job: job.created_at, reverse=True)[:limit])

    def count_active(self, connection_id):
        return sum(
            job.connection_id == connection_id and job.status in ACTIVE_STATUSES
            for job in self.rows.values()
        )


class FakeQueue:
    def __init__(self):
        self.jobs = []
        self.previews = []

    def enqueue_job(self, job_id):
        self.jobs.append(job_id)

    def enqueue_preview(self, connection_id, file_key):
        self.previews.append((connection_id, file_key))


class FakeEngine:
    """Does what the test tells it to: return a result, raise, or run a callback mid-job."""

    def __init__(self, result=None, error=None, during=None):
        self.result = result or TransformResult(rows_total=10, rows_changed=4)
        self.error = error
        self.during = during
        self.runs = 0

    def run(self, job, connection, destination, on_progress, should_cancel):
        self.runs += 1
        on_progress(0.5, "Transforming")
        if self.during:
            self.during(job, should_cancel)
        if self.error:
            raise self.error
        return self.result


class FakeResults:
    def __init__(self, rows=None):
        self.rows = rows
        self.deleted = []

    def path_for(self, job_id):
        return f"/results/{job_id}"

    def read_rows(self, job_id, offset, limit):
        if self.rows is None:
            return None
        return ["id", "email"], self.rows[offset : offset + limit]

    def delete(self, job_id):
        self.deleted.append(job_id)

    def purge_older_than(self, seconds):
        pass
