"""Composition root: the one place that wires infrastructure adapters into services.

Views and Celery tasks get their services from here, so neither needs to import infrastructure.
"""

from datetime import timedelta
from functools import cache

from django.conf import settings

from infrastructure.celery_queue import CeleryTaskQueue
from infrastructure.credential_vault import EncryptedCredentialVault
from infrastructure.file_inspector import S3FileInspector
from infrastructure.job_repository import DjangoJobRepository
from infrastructure.preview_store import CachePreviewStore
from infrastructure.result_store import ParquetResultStore
from infrastructure.s3_storage import S3Storage
from services.connections import ConnectionService
from services.jobs import JobService
from services.patterns import PatternService
from services.pii import PiiService
from services.previews import PreviewService
from services.standardise import StandardiseService


@cache
def connection_service() -> ConnectionService:
    return ConnectionService(
        storage=S3Storage(),
        vault=EncryptedCredentialVault(
            key=settings.CREDENTIAL_ENCRYPTION_KEY,
            idle_ttl=settings.CONNECTION_IDLE_TTL,
            max_age=settings.CONNECTION_MAX_AGE,
        ),
    )


def _engine():
    # Imported on demand, so the reference engine (and most of the test suite) runs without
    # PySpark ever being loaded.
    if settings.TRANSFORM_ENGINE == "streaming":
        from infrastructure.streaming_engine import StreamingEngine

        return StreamingEngine()
    from infrastructure.spark_engine import SparkEngine

    return SparkEngine(
        master=settings.SPARK_MASTER_URL,
        staging_dir=settings.RESULTS_DIR,
        conf=settings.SPARK_CONF,
        s3_endpoint=settings.S3_ENDPOINT_URL,
    )


@cache
def pattern_service() -> PatternService:
    from infrastructure.claude_pattern_writer import (
        INSTRUCTIONS_VERSION,
        ClaudePatternWriter,
        UnconfiguredPatternWriter,
    )
    from infrastructure.pattern_cache import CachePatternStore
    from infrastructure.pattern_probe import SubprocessPatternProbe

    if settings.ANTHROPIC_API_KEY:
        writer = ClaudePatternWriter(
            settings.ANTHROPIC_API_KEY, settings.LLM_MODEL, settings.LLM_TIMEOUT
        )
    else:
        writer = UnconfiguredPatternWriter()
    return PatternService(
        writer=writer,
        cache=CachePatternStore(
            kind="pattern",
            namespace=f"{settings.LLM_MODEL}:v{INSTRUCTIONS_VERSION}",
            ttl=settings.PATTERN_CACHE_TTL,
        ),
        probe=SubprocessPatternProbe(),
    )


def _advice_cache():
    from infrastructure import claude_data_advisers as advisers
    from infrastructure.pattern_cache import CacheStore

    return CacheStore(
        kind="advice",
        namespace=f"{settings.LLM_MODEL}:v{advisers.INSTRUCTIONS_VERSION}",
        ttl=settings.PATTERN_CACHE_TTL,
    )


def _claude_arguments():
    """Without an API key these adapters are never reached: such a job is refused at submit."""
    return settings.ANTHROPIC_API_KEY, settings.LLM_MODEL, settings.LLM_TIMEOUT


@cache
def pii_service() -> PiiService:
    from infrastructure.claude_data_advisers import ClaudePiiClassifier

    return PiiService(ClaudePiiClassifier(*_claude_arguments()), _advice_cache(), pattern_service())


@cache
def standardise_service() -> StandardiseService:
    from infrastructure.claude_data_advisers import ClaudeValueStandardiser

    return StandardiseService(ClaudeValueStandardiser(*_claude_arguments()), _advice_cache())


@cache
def job_service() -> JobService:
    return JobService(
        connections=connection_service(),
        jobs=DjangoJobRepository(),
        queue=CeleryTaskQueue(),
        engine=_engine(),
        results=ParquetResultStore(settings.RESULTS_DIR),
        patterns=pattern_service(),
        pii=pii_service(),
        standardiser=standardise_service(),
        max_active_jobs=settings.JOB_MAX_ACTIVE_PER_CONNECTION,
        max_attempts=settings.JOB_MAX_ATTEMPTS,
        stale_after=timedelta(seconds=settings.JOB_STALE_AFTER),
        results_max_age=timedelta(seconds=settings.CONNECTION_MAX_AGE),
    )


@cache
def preview_service() -> PreviewService:
    return PreviewService(
        connections=connection_service(),
        inspector=S3FileInspector(),
        store=CachePreviewStore(ttl=settings.CONNECTION_IDLE_TTL),
        queue=CeleryTaskQueue(),
    )
