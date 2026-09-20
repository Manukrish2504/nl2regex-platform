import logging

import pytest
from rest_framework.test import APIClient

from api.views import CONNECTION_COOKIE
from domain import errors
from infrastructure.s3_storage import S3Storage

pytestmark = pytest.mark.django_db  # disconnecting also forgets the connection's jobs
SECRET = "wJalrXUtnFEMI-not-a-real-secret-EXAMPLEKEY"


@pytest.fixture
def client():
    return APIClient()


def _connect(client, bucket, secret=SECRET):
    body = {"access_key_id": "AKIAEXAMPLEEXAMPLE00", "secret_access_key": secret, "bucket": bucket}
    return client.post("/api/connection/", body, format="json")


def test_connect_never_reveals_the_secret(client, s3_bucket, caplog):
    caplog.set_level(logging.DEBUG)
    response = _connect(client, s3_bucket)

    assert response.status_code == 201
    assert response.json() == {"bucket": s3_bucket, "region": "eu-north-1"}
    for place in (response.content.decode(), str(response.cookies), caplog.text):
        assert SECRET not in place


def test_connection_cookie_is_locked_down(client, s3_bucket):
    cookie = _connect(client, s3_bucket).cookies[CONNECTION_COOKIE]

    assert cookie["httponly"] is True
    assert cookie["secure"] is True  # tests run with DEBUG off, like production
    assert cookie["samesite"] == "Strict"
    assert cookie["path"] == "/api"
    assert cookie["max-age"] == ""  # a session cookie: the vault is the only expiry clock


def test_connection_lifecycle(client, s3_bucket):
    assert client.get("/api/connection/").status_code == 401

    _connect(client, s3_bucket)
    assert client.get("/api/connection/").json() == {"bucket": s3_bucket, "region": "eu-north-1"}

    assert client.delete("/api/connection/").status_code == 204
    assert client.get("/api/connection/").status_code == 401


def test_file_listing(client, s3_bucket):
    _connect(client, s3_bucket)
    body = client.get("/api/connection/files/", {"prefix": "samples/"}).json()

    assert body["prefix"] == "samples/"
    assert body["folders"] == ["samples/archive/"]
    assert body["next_token"] is None
    assert {file["key"]: file["format"] for file in body["files"]} == {
        "samples/REPORT.XLSX": "excel",
        "samples/customers.csv": "csv",
        "samples/notes.txt": None,
    }
    assert set(body["files"][0]) == {"key", "size", "last_modified", "format"}


def test_file_listing_needs_a_connection(client):
    response = client.get("/api/connection/files/")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "connection_not_found"


@pytest.mark.parametrize(
    ("failure", "status"),
    [
        (errors.InvalidCredentials(), 400),
        (errors.BucketAccessDenied(), 403),
        (errors.BucketNotFound(), 404),
        (errors.StorageUnreachable(), 502),
        (errors.StorageError("SlowDown"), 502),
    ],
)
def test_domain_errors_map_to_status_codes(client, monkeypatch, failure, status):
    def fail(self, credentials, bucket):
        raise failure

    monkeypatch.setattr(S3Storage, "resolve_bucket", fail)
    response = _connect(client, "some-bucket")

    assert response.status_code == status
    assert response.json() == {"error": {"code": failure.code, "message": failure.message}}
    assert CONNECTION_COOKIE not in response.cookies


def test_unexpected_errors_answer_in_the_same_shape_without_details(client, monkeypatch):
    def explode(self, credentials, bucket):
        raise RuntimeError(f"boom {credentials.secret_access_key}")

    monkeypatch.setattr(S3Storage, "resolve_bucket", explode)
    response = _connect(client, "some-bucket")

    assert response.status_code == 500
    assert response.json()["error"]["code"] == "internal_error"
    assert SECRET not in response.content.decode()


@pytest.mark.parametrize(
    "body",
    [
        {"access_key_id": "lowercase-key-id-000", "secret_access_key": SECRET, "bucket": "ok-name"},
        {
            "access_key_id": "AKIAEXAMPLEEXAMPLE00",
            "secret_access_key": "short",
            "bucket": "ok-name",
        },
        {
            "access_key_id": "AKIAEXAMPLEEXAMPLE00",
            "secret_access_key": SECRET,
            "bucket": "Bad_Name",
        },
        {"access_key_id": "AKIAEXAMPLEEXAMPLE00", "secret_access_key": SECRET, "bucket": "ab"},
        {},
    ],
)
def test_invalid_input_is_rejected_before_reaching_s3(client, body):
    response = client.post("/api/connection/", body, format="json")
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "validation_error"
    assert SECRET not in response.content.decode()


def test_html_form_posts_are_refused(client):
    # The login-CSRF vector: a cross-site form needs no preflight, so it must not be parsed at all.
    response = client.post(
        "/api/connection/",
        "access_key_id=AKIAEXAMPLEEXAMPLE00&bucket=attacker-bucket",
        content_type="application/x-www-form-urlencoded",
    )
    assert response.status_code == 415


def test_connect_attempts_are_rate_limited(client):
    statuses = [client.post("/api/connection/", {}, format="json").status_code for _ in range(11)]
    assert statuses == [400] * 10 + [429]


def test_reading_the_connection_is_not_rate_limited(client):
    statuses = {client.get("/api/connection/").status_code for _ in range(15)}
    assert statuses == {401}
