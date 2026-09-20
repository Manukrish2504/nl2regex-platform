import io
from itertools import islice

from domain.connections import Connection, FileFormat
from domain.tables import FilePreview
from infrastructure import tabular
from infrastructure.s3_storage import read_first_lines
from infrastructure.streaming_engine import downloaded_excel

PREVIEW_ROWS = 20


class S3FileInspector:
    def preview(
        self, connection: Connection, file_key: str, file_format: FileFormat
    ) -> FilePreview:
        if file_format is FileFormat.CSV:
            return self._preview_csv(connection, file_key)
        return self._preview_excel(connection, file_key)

    def _preview_csv(self, connection: Connection, file_key: str) -> FilePreview:
        """Only the first 256 KB is downloaded, however large the file is."""
        head = read_first_lines(connection, file_key, tabular.CSV_HEAD_BYTES)
        return _preview(tabular.csv_rows(io.BufferedReader(io.BytesIO(head))))

    def _preview_excel(self, connection: Connection, file_key: str) -> FilePreview:
        """An .xlsx is a zip archive, so all of it has to be downloaded before any row is read."""
        with downloaded_excel(connection, file_key, lambda *_: None) as workbook:
            return _preview(tabular.excel_rows(workbook))


def _preview(rows) -> FilePreview:
    columns = tabular.read_header(rows)
    return FilePreview(
        columns, [tabular.fit(row, len(columns)) for row in islice(rows, PREVIEW_ROWS)]
    )
