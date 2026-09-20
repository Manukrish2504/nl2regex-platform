"""Use-cases for connecting to a user's bucket. Imports only the standard library and the domain."""

import hashlib
import secrets

from domain.connections import Connection, FileListing, S3Credentials
from domain.errors import ConnectionNotFound
from domain.ports import CredentialVault, ObjectStorage


def connection_id_for(token: str) -> str:
    """The server keeps only this digest of the browser's token, the way API keys are stored hashed.

    A leaked database or Redis dump therefore contains nothing a browser could replay.
    """
    return hashlib.sha256(token.encode()).hexdigest()


class ConnectionService:
    def __init__(self, storage: ObjectStorage, vault: CredentialVault):
        self._storage = storage
        self._vault = vault

    def connect(
        self, credentials: S3Credentials, bucket: str, previous_token: str | None = None
    ) -> tuple[str, Connection]:
        """Validate against S3 first, so a failed attempt never stores anything."""
        region = self._storage.resolve_bucket(credentials, bucket)
        self.disconnect(previous_token)

        token = secrets.token_urlsafe(32)
        connection = Connection(connection_id_for(token), bucket, region, credentials)
        self._vault.store(connection)
        return token, connection

    def get(self, token: str | None) -> Connection:
        connection = self._vault.load(connection_id_for(token)) if token else None
        if connection is None:
            raise ConnectionNotFound()
        return connection

    def get_by_id(self, connection_id: str) -> Connection:
        """For background workers, which hold a connection ID but never the browser's token."""
        connection = self._vault.load(connection_id)
        if connection is None:
            raise ConnectionNotFound()
        return connection

    def list_files(self, token: str | None, prefix: str, page_token: str | None) -> FileListing:
        return self._storage.list_files(self.get(token), prefix, page_token)

    def disconnect(self, token: str | None) -> None:
        if token:
            self._vault.delete(connection_id_for(token))
