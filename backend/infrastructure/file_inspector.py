import io
import tempfile
from itertools import islice
from pathlib import Path

from domain.connections import Connection, FileFormat
from domain.errors import FileTooLarge
from domain.tables import FilePreview
from infrastructure import tabular
from infrastructure.s3_storage import open_object, translated_errors

PREVIEW_ROWS = 20
CSV_HEAD_BYTES = 256 * 1024


class S3FileInspector:
    def preview(
        self, connection: Connection, file_key: str, file_format: FileFormat
    ) -> FilePreview:
        if file_format is FileFormat.CSV:
            return self._preview_csv(connection, file_key)
        return self._preview_excel(connection, file_key)

    def _preview_csv(self, connection: Connection, file_key: str) -> FilePreview:
        """Only the first 256 KB is downloaded, however large the file is."""
        body, size = open_object(connection, file_key, first_bytes=CSV_HEAD_BYTES)
        with translated_errors(connection.bucket):
            head = body.read()
        truncated = size > len(head)
        if truncated:
            head = head[: head.rfind(b"\n") + 1]  # drop the line the cut went through

        rows = tabular.csv_rows(io.BufferedReader(io.BytesIO(head)))
        return _preview(rows)

    def _preview_excel(self, connection: Connection, file_key: str) -> FilePreview:
        """An .xlsx is a zip archive, so all of it has to be downloaded before any row is read."""
        body, size = open_object(connection, file_key)
        if size > tabular.EXCEL_MAX_BYTES:
            raise FileTooLarge()
        with tempfile.NamedTemporaryFile(suffix=".xlsx") as local:
            with translated_errors(connection.bucket):
                for chunk in body.iter_chunks(1024 * 1024):
                    local.write(chunk)
            local.flush()
            return _preview(tabular.excel_rows(Path(local.name)))


def _preview(rows) -> FilePreview:
    columns = tabular.read_header(rows)
    return FilePreview(
        columns, [tabular.fit(row, len(columns)) for row in islice(rows, PREVIEW_ROWS)]
    )
