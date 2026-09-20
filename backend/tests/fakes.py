"""In-memory stand-ins for the ports, so services are tested without a database, S3 or Celery."""

import copy
from contextlib import contextmanager

from domain.connections import FileListing
from domain.jobs import ACTIVE_STATUSES, JobCancelled, JobStatus, TransformResult


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
    """Stands in for an engine. `during` runs while the file is being rewritten, so that a test
    can act in the middle of a job."""

    def __init__(self, result=None, error=None, during=None, columns=None, rows=None, counts=None):
        self.result = result or TransformResult(rows_total=10, rows_changed=4)
        self.error, self.during = error, during
        self.columns = columns or ["id", "email"]
        self.rows, self.counts = rows or [], counts or []
        self.runs = 0
        self.operations = None  # what the last rewrite was asked to do

    @contextmanager
    def open(self, job, connection, on_progress, should_cancel):
        self._job, self._should_cancel = job, should_cancel
        yield self

    def sample(self, limit):
        return self.rows[:limit]

    def distinct_values(self, column, limit, on_progress):
        return self.counts[:limit]

    def rewrite(self, operations, destination, on_progress):
        self.runs += 1
        self.operations = operations
        on_progress(0.5, "Transforming")
        if self.during:
            self.during(self._job, self._should_cancel)
        if self.error:
            raise self.error
        if self._should_cancel():
            raise JobCancelled()
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


class FakeWriter:
    """Stands in for the language model. Answers come from a list, one per call."""

    is_configured = True

    def __init__(self, *answers):
        self.answers = list(answers)
        self.calls = []  # (request, rejected) for every call made

    def write(self, request, rejected=None):
        self.calls.append((request, rejected))
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer


class FakePatternCache:
    def __init__(self):
        self.entries = {}

    def get(self, request):
        return self.entries.get(request)

    def put(self, request, suggestion):
        self.entries[request] = suggestion


class FakeProbe:
    """Refuses exactly the patterns it is told are unsafe."""

    def __init__(self, unsafe=()):
        self.unsafe = set(unsafe)
        self.checked = []

    def check(self, pattern):
        from domain.errors import UnsafePattern

        self.checked.append(pattern)
        if pattern in self.unsafe:
            raise UnsafePattern("it did not finish on the input 'aaaa!'")


class FakeClassifier:
    def __init__(self, findings=()):
        self.findings = list(findings)
        self.calls = []  # the profiles it was shown

    def classify(self, profiles):
        self.calls.append(profiles)
        return self.findings


class FakeStandardiser:
    def __init__(self, pairs=()):
        self.pairs = list(pairs)
        self.calls = []  # (column, values, instruction)

    def standardise(self, column, values, instruction):
        self.calls.append((column, values, instruction))
        return self.pairs


class FakeAdviceCache:
    def __init__(self):
        self.entries = {}

    def get(self, key):
        return self.entries.get(key)

    def put(self, key, advice):
        self.entries[key] = advice


def run_replace(
    engine, job, connection, destination, on_progress=lambda *_: None, should_cancel=lambda: False
):
    """Run a job's single find-and-replace through an engine, the way the job service does."""
    with engine.open(job, connection, on_progress, should_cancel) as opened:
        return opened.rewrite([job.as_replace()], destination, on_progress)
