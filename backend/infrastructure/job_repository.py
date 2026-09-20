from domain.connections import FileFormat
from domain.jobs import ACTIVE_STATUSES, Job, JobStatus
from infrastructure.models import JobRecord

# Everything a status change may write. cancel_requested is absent on purpose: only
# request_cancel() writes it, so a worker saving its state can never erase a cancel request.
_MUTABLE_FIELDS = (
    # A job that came with a prompt gets these from the worker that wrote its pattern.
    "pattern",
    "replacement",
    "columns",
    "explanation",
    "pattern_source",
    "report",
    "status",
    "progress",
    "stage",
    "attempts",
    "error_code",
    "error_message",
    "rows_total",
    "rows_changed",
    "started_at",
    "finished_at",
)


class DjangoJobRepository:
    def add(self, job: Job) -> None:
        JobRecord.objects.create(
            id=job.id,
            connection_id=job.connection_id,
            file_key=job.file_key,
            file_format=job.file_format.value,
            prompt=job.prompt,
            kind=job.kind,
            cancel_requested=job.cancel_requested,
            created_at=job.created_at,
            **_mutable_values(job),
        )

    def get(self, job_id: str) -> Job | None:
        record = JobRecord.objects.filter(id=job_id).first()
        return _to_job(record) if record else None

    def save(self, job: Job, expected_status: JobStatus, expected_attempts: int) -> bool:
        # One UPDATE ... WHERE: the database decides the winner, with no locks and no read first.
        updated = JobRecord.objects.filter(
            id=job.id, status=expected_status.value, attempts=expected_attempts
        ).update(**_mutable_values(job))
        return updated == 1

    def save_progress(self, job_id: str, progress: int, stage: str) -> None:
        JobRecord.objects.filter(id=job_id, status=JobStatus.RUNNING.value).update(
            progress=progress, stage=stage
        )

    def request_cancel(self, job_id: str) -> bool:
        updated = JobRecord.objects.filter(id=job_id, status=JobStatus.RUNNING.value).update(
            cancel_requested=True
        )
        return updated == 1

    def is_cancel_requested(self, job_id: str) -> bool:
        return JobRecord.objects.filter(id=job_id, cancel_requested=True).exists()

    def list_for_connection(self, connection_id: str, limit: int) -> list[Job]:
        records = JobRecord.objects.filter(connection_id=connection_id).order_by("-created_at")
        return [_to_job(record) for record in records[:limit]]

    def count_active(self, connection_id: str) -> int:
        return JobRecord.objects.filter(
            connection_id=connection_id, status__in=[status.value for status in ACTIVE_STATUSES]
        ).count()


def _mutable_values(job: Job) -> dict:
    values = {name: getattr(job, name) for name in _MUTABLE_FIELDS}
    values["status"] = job.status.value
    return values


def _to_job(record: JobRecord) -> Job:
    return Job(
        id=str(record.id),
        connection_id=record.connection_id,
        file_key=record.file_key,
        file_format=FileFormat(record.file_format),
        pattern=record.pattern,
        replacement=record.replacement,
        columns=list(record.columns),
        created_at=record.created_at,
        kind=record.kind,
        prompt=record.prompt,
        report=record.report,
        explanation=record.explanation,
        pattern_source=record.pattern_source,
        status=JobStatus(record.status),
        progress=record.progress,
        stage=record.stage,
        attempts=record.attempts,
        cancel_requested=record.cancel_requested,
        error_code=record.error_code,
        error_message=record.error_message,
        rows_total=record.rows_total,
        rows_changed=record.rows_changed,
        started_at=record.started_at,
        finished_at=record.finished_at,
    )
