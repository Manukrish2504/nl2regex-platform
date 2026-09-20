import io

import pytest
from fakes import FakeQueue, FakeStorage, FakeVault
from openpyxl import Workbook

from domain import errors
from domain.connections import FileFormat, S3Credentials
from domain.tables import FilePreview
from infrastructure import file_inspector, tabular
from infrastructure.file_inspector import S3FileInspector
from infrastructure.preview_store import CachePreviewStore
from services.connections import ConnectionService
from services.previews import PreviewService

# --- the inspector, against fake S3 -------------------------------------------------------


def test_csv_preview_has_the_columns_and_first_rows(connection, put_object):
    body = b"id,email\n" + b"".join(b"%d,user%d@example.com\n" % (n, n) for n in range(100))
    preview = S3FileInspector().preview(connection, put_object("c.csv", body), FileFormat.CSV)

    assert preview.columns == ["id", "email"]
    assert len(preview.rows) == file_inspector.PREVIEW_ROWS
    assert preview.rows[0] == ["0", "user0@example.com"]


def test_csv_preview_downloads_only_the_head_of_a_large_file(connection, put_object, monkeypatch):
    monkeypatch.setattr(tabular, "CSV_HEAD_BYTES", 200)
    body = b"id,email\n" + b"".join(b"%d,user%d@example.com\n" % (n, n) for n in range(5000))
    preview = S3FileInspector().preview(connection, put_object("big.csv", body), FileFormat.CSV)

    # 200 bytes hold the header and a handful of rows. The row the cut went through is dropped,
    # so no partial line ever shows up as data.
    assert 1 <= len(preview.rows) < 10
    assert all(row[1] == f"user{row[0]}@example.com" for row in preview.rows)


def test_excel_preview(connection, put_object):
    workbook = Workbook()
    workbook.active.append(["id", "email"])
    workbook.active.append([1, "a@x.com"])
    buffer = io.BytesIO()
    workbook.save(buffer)

    preview = S3FileInspector().preview(
        connection, put_object("book.xlsx", buffer.getvalue()), FileFormat.EXCEL
    )
    assert preview == FilePreview(["id", "email"], [["1", "a@x.com"]])


def test_preview_of_an_empty_or_missing_file_fails_clearly(connection, put_object):
    with pytest.raises(errors.FileUnreadable, match="empty"):
        S3FileInspector().preview(connection, put_object("empty.csv", b""), FileFormat.CSV)
    with pytest.raises(errors.ObjectNotFound):
        S3FileInspector().preview(connection, "gone.csv", FileFormat.CSV)


# --- the service: claim once, build in the background, poll ------------------------------


class StubInspector:
    def __init__(self, outcome):
        self.outcome = outcome

    def preview(self, connection, file_key, file_format):
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


def make_service(outcome):
    connections = ConnectionService(FakeStorage(), FakeVault())
    queue = FakeQueue()
    service = PreviewService(connections, StubInspector(outcome), CachePreviewStore(ttl=60), queue)
    token, connection = connections.connect(
        S3Credentials("AKIAEXAMPLEEXAMPLE00", "secret"), "bucket"
    )
    return service, queue, token, connection


def test_the_first_request_starts_one_background_read_and_later_ones_wait():
    service, queue, token, connection = make_service(FilePreview(["id"], [["1"]]))

    assert service.get(token, "a.csv") == {"status": "pending"}
    assert service.get(token, "a.csv") == {"status": "pending"}
    assert queue.previews == [(connection.id, "a.csv")]  # enqueued once, not per poll

    service.build(connection.id, "a.csv")  # what the worker does
    assert service.get(token, "a.csv") == {"status": "done", "columns": ["id"], "rows": [["1"]]}


def test_a_failed_read_is_reported_with_its_reason():
    service, _, token, connection = make_service(errors.FileUnreadable("The file is empty."))
    service.get(token, "a.csv")
    service.build(connection.id, "a.csv")

    assert service.get(token, "a.csv") == {
        "status": "failed",
        "error": {"code": "file_unreadable", "message": "The file is empty."},
    }


def test_previews_need_a_connection_and_a_supported_file():
    service, queue, token, _ = make_service(FilePreview([], []))
    with pytest.raises(errors.ConnectionNotFound):
        service.get("unknown-token", "a.csv")
    with pytest.raises(errors.UnsupportedFile):
        service.get(token, "notes.txt")
    assert queue.previews == []


def test_previews_are_private_to_a_connection():
    service, queue, token, connection = make_service(FilePreview(["id"], [["1"]]))
    service.get(token, "a.csv")
    service.build(connection.id, "a.csv")

    other_token, other = service._connections.connect(
        S3Credentials("AKIAEXAMPLEEXAMPLE00", "secret"), "bucket"
    )
    assert service.get(other_token, "a.csv") == {"status": "pending"}  # not the first one's data
    assert queue.previews[-1] == (other.id, "a.csv")
