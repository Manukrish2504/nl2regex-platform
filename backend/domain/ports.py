"""What the application needs from the outside world. Infrastructure implements these."""

from typing import Protocol

from domain.connections import Connection, FileListing, S3Credentials


class ObjectStorage(Protocol):
    def resolve_bucket(self, credentials: S3Credentials, bucket: str) -> str:
        """Prove the credentials can list the bucket and return its region. Raises a DomainError."""
        ...

    def list_files(
        self, connection: Connection, prefix: str, page_token: str | None
    ) -> FileListing:
        """One page of the folders and files directly under `prefix`."""
        ...


class CredentialVault(Protocol):
    def store(self, connection: Connection) -> None: ...

    def load(self, connection_id: str) -> Connection | None:
        """The connection, or None if it is unknown, expired or fails its integrity check."""
        ...

    def delete(self, connection_id: str) -> None: ...
