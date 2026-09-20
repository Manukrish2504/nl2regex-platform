"""File previews: column names and first rows, read in the background and polled by the browser."""

import logging

from domain.connections import FileFormat
from domain.errors import DomainError, UnsupportedFile
from domain.ports import FileInspector, PreviewStore, TaskQueue
from services.connections import ConnectionService

logger = logging.getLogger(__name__)

PENDING = {"status": "pending"}


class PreviewService:
    def __init__(
        self,
        connections: ConnectionService,
        inspector: FileInspector,
        store: PreviewStore,
        queue: TaskQueue,
    ):
        self._connections = connections
        self._inspector = inspector
        self._store = store
        self._queue = queue

    def get(self, token: str | None, file_key: str) -> dict:
        """The preview if it is ready. Otherwise start building it (once) and report "pending"."""
        connection = self._connections.get(token)
        if FileFormat.from_key(file_key) is None:
            raise UnsupportedFile()

        entry = self._store.get(connection.id, file_key)
        if entry is not None:
            return entry
        if self._store.mark_pending(connection.id, file_key):
            self._queue.enqueue_preview(connection.id, file_key)
        return PENDING

    def build(self, connection_id: str, file_key: str) -> None:
        """The worker side. Reading a file is parsing, and parsing never runs in the web process."""
        try:
            connection = self._connections.get_by_id(connection_id)
            preview = self._inspector.preview(connection, file_key, FileFormat.from_key(file_key))
            entry = {"status": "done", "columns": preview.columns, "rows": preview.rows}
        except DomainError as error:
            entry = {"status": "failed", "error": {"code": error.code, "message": error.message}}
        self._store.put(connection_id, file_key, entry)
