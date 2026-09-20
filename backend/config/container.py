"""Composition root: the one place that wires infrastructure adapters into services.

Views and Celery tasks get their services from here, so neither needs to import infrastructure.
"""

from functools import cache

from django.conf import settings

from infrastructure.credential_vault import EncryptedCredentialVault
from infrastructure.s3_storage import S3Storage
from services.connections import ConnectionService


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
