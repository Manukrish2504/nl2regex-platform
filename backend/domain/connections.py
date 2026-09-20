"""Entities for an S3 connection. The domain package imports only the standard library."""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum


@dataclass(frozen=True)
class S3Credentials:
    access_key_id: str
    secret_access_key: str

    def __repr__(self):
        # Credentials must never reach a log line or traceback, so the repr shows neither in full.
        return f"S3Credentials(access_key_id='...{self.access_key_id[-4:]}')"


@dataclass(frozen=True)
class Connection:
    """A validated link to one bucket. `id` is the SHA-256 of the browser's token, not the token."""

    id: str
    bucket: str
    region: str
    credentials: S3Credentials


class FileFormat(Enum):
    CSV = "csv"
    EXCEL = "excel"

    @classmethod
    def from_key(cls, key: str) -> "FileFormat | None":
        lowered = key.lower()
        if lowered.endswith(".csv"):
            return cls.CSV
        if lowered.endswith(".xlsx"):
            return cls.EXCEL
        return None


@dataclass(frozen=True)
class S3File:
    key: str
    size: int
    last_modified: datetime
    format: FileFormat | None  # None means the app cannot process this file


@dataclass(frozen=True)
class FileListing:
    folders: list[str]
    files: list[S3File]
    next_token: str | None
