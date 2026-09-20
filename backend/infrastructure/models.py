import uuid

from django.db import models


class JobRecord(models.Model):
    """The stored form of domain.jobs.Job. DjangoJobRepository maps between the two."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    connection_id = models.CharField(max_length=64)
    file_key = models.CharField(max_length=1024)
    file_format = models.CharField(max_length=16)
    pattern = models.TextField(blank=True)  # empty until written, for a job that came as a prompt
    replacement = models.TextField(blank=True)
    columns = models.JSONField(default=list)
    prompt = models.TextField(null=True)
    explanation = models.TextField(null=True)
    pattern_source = models.CharField(max_length=8, default="user")
    kind = models.CharField(max_length=16, default="replace")
    report = models.JSONField(null=True)
    status = models.CharField(max_length=16)
    progress = models.PositiveSmallIntegerField(default=0)
    stage = models.CharField(max_length=300, blank=True)
    attempts = models.PositiveSmallIntegerField(default=0)
    cancel_requested = models.BooleanField(default=False)
    error_code = models.CharField(max_length=64, null=True)
    error_message = models.TextField(null=True)
    rows_total = models.BigIntegerField(null=True)
    rows_changed = models.BigIntegerField(null=True)
    created_at = models.DateTimeField()
    started_at = models.DateTimeField(null=True)
    finished_at = models.DateTimeField(null=True)

    class Meta:
        db_table = "jobs"
        indexes = [models.Index(fields=["connection_id", "-created_at"], name="jobs_by_connection")]
