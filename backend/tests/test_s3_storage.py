import pytest
from botocore.exceptions import (
    ClientError,
    ConnectTimeoutError,
    EndpointConnectionError,
    ParamValidationError,
    ReadTimeoutError,
)

from domain import errors
from domain.connections import Connection, FileFormat, S3Credentials
from infrastructure import s3_storage
from infrastructure.s3_storage import S3Storage, translate

REGION = "eu-north-1"  # where conftest's s3_bucket lives
CREDENTIALS = S3Credentials("AKIAEXAMPLEEXAMPLE00", "not-a-real-secret-key")


def _connection(bucket):
    return Connection("a" * 64, bucket, REGION, CREDENTIALS)


def test_resolve_bucket_returns_the_buckets_own_region(s3_bucket):
    assert S3Storage().resolve_bucket(CREDENTIALS, s3_bucket) == REGION


def test_resolve_bucket_reports_a_missing_bucket(s3_bucket):
    with pytest.raises(errors.BucketNotFound):
        S3Storage().resolve_bucket(CREDENTIALS, "no-such-bucket-here")


def test_root_listing_separates_folders_from_files(s3_bucket):
    listing = S3Storage().list_files(_connection(s3_bucket), "", None)
    assert listing.folders == ["samples/"]
    assert [file.key for file in listing.files] == ["readme.txt"]
    assert listing.next_token is None


def test_folder_listing_detects_formats_and_hides_the_folder_marker(s3_bucket):
    listing = S3Storage().list_files(_connection(s3_bucket), "samples/", None)
    assert listing.folders == ["samples/archive/"]
    assert {file.key: file.format for file in listing.files} == {
        "samples/REPORT.XLSX": FileFormat.EXCEL,  # extensions match case-insensitively
        "samples/customers.csv": FileFormat.CSV,
        "samples/notes.txt": None,
    }
    assert all(file.size == 4 for file in listing.files)


def test_listing_pages_through_with_the_continuation_token(s3_bucket, monkeypatch):
    monkeypatch.setattr(s3_storage, "PAGE_SIZE", 2)
    storage, connection = S3Storage(), _connection(s3_bucket)

    seen, token = [], None
    for _ in range(5):
        page = storage.list_files(connection, "samples/", token)
        seen += page.folders + [file.key for file in page.files]
        token = page.next_token
        if token is None:
            break

    assert sorted(seen) == [
        "samples/REPORT.XLSX",
        "samples/archive/",
        "samples/customers.csv",
        "samples/notes.txt",
    ]


def _client_error(code):
    return ClientError({"Error": {"Code": code}, "ResponseMetadata": {"RequestId": "r1"}}, "op")


@pytest.mark.parametrize(
    ("failure", "expected"),
    [
        (_client_error("InvalidAccessKeyId"), errors.InvalidCredentials),
        (_client_error("SignatureDoesNotMatch"), errors.InvalidCredentials),
        (_client_error("AuthorizationHeaderMalformed"), errors.InvalidCredentials),
        (_client_error("ExpiredToken"), errors.InvalidCredentials),
        (_client_error("NoSuchBucket"), errors.BucketNotFound),
        (_client_error("404"), errors.BucketNotFound),
        (_client_error("AccessDenied"), errors.BucketAccessDenied),
        (_client_error("403"), errors.BucketAccessDenied),
        (_client_error("InvalidArgument"), errors.InvalidPageToken),
        (_client_error("SlowDown"), errors.StorageError),
        (
            EndpointConnectionError(endpoint_url="https://s3.amazonaws.com"),
            errors.StorageUnreachable,
        ),
        (ConnectTimeoutError(endpoint_url="https://s3.amazonaws.com"), errors.StorageUnreachable),
        (ReadTimeoutError(endpoint_url="https://s3.amazonaws.com"), errors.StorageUnreachable),
        (ParamValidationError(report="bad"), errors.StorageError),
    ],
)
def test_translate(failure, expected):
    assert type(translate(failure)) is expected


def test_unknown_aws_codes_are_reported_not_hidden():
    assert "SlowDown" in translate(_client_error("SlowDown")).message
