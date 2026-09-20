import logging
from contextlib import contextmanager

import boto3
from botocore import exceptions as boto_errors
from botocore.config import Config

from domain.connections import Connection, FileFormat, FileListing, S3Credentials, S3File
from domain.errors import (
    BucketAccessDenied,
    BucketNotFound,
    DomainError,
    FileUnreadable,
    InvalidCredentials,
    InvalidPageToken,
    ObjectNotFound,
    StorageError,
    StorageUnreachable,
)

logger = logging.getLogger(__name__)

PAGE_SIZE = 200

# Short timeouts and a single retry: these calls run inside a web request.
_CONFIG = Config(
    connect_timeout=5,
    read_timeout=10,
    retries={"total_max_attempts": 2, "mode": "standard"},
)

# The bucket's region is unknown until we ask. Pinning the first client to one region keeps
# behaviour independent of the container's environment; botocore follows S3's redirect itself.
_DISCOVERY_REGION = "us-east-1"

_ERRORS_BY_AWS_CODE: dict[str, type[DomainError]] = {
    "InvalidAccessKeyId": InvalidCredentials,
    "SignatureDoesNotMatch": InvalidCredentials,
    "AuthorizationHeaderMalformed": InvalidCredentials,
    "InvalidToken": InvalidCredentials,
    "ExpiredToken": InvalidCredentials,
    "NoSuchBucket": BucketNotFound,
    "404": BucketNotFound,  # HEAD responses carry no body, only the status
    "AccessDenied": BucketAccessDenied,
    "AllAccessDisabled": BucketAccessDenied,
    "403": BucketAccessDenied,
    "InvalidArgument": InvalidPageToken,  # a continuation token S3 does not recognise
    "NoSuchKey": ObjectNotFound,
}


def translate(error: Exception) -> DomainError:
    """Map any botocore failure to a domain error. Unknown failures keep their AWS code."""
    if isinstance(error, boto_errors.ClientError):
        aws_code = error.response.get("Error", {}).get("Code", "Unknown")
        if aws_code == "InvalidRange":  # a ranged read of a zero-byte object
            return FileUnreadable("The file is empty.")
        domain_error = _ERRORS_BY_AWS_CODE.get(aws_code)
        return domain_error() if domain_error else StorageError(aws_code)
    if isinstance(error, (boto_errors.ConnectionError, boto_errors.HTTPClientError)):
        return StorageUnreachable()
    return StorageError(type(error).__name__)


class S3Storage:
    def resolve_bucket(self, credentials: S3Credentials, bucket: str) -> str:
        client = client_for(credentials, _DISCOVERY_REGION)
        with translated_errors(bucket):
            # A GET first: its error body names the exact problem (bad key, bad signature, no such
            # bucket, no permission). A HEAD can only say 403 or 404.
            client.list_objects_v2(Bucket=bucket, MaxKeys=1)
            head = client.head_bucket(Bucket=bucket)

        headers = head["ResponseMetadata"]["HTTPHeaders"]
        region = head.get("BucketRegion") or headers.get("x-amz-bucket-region")
        if not region:
            raise StorageError("MissingBucketRegion")
        return region

    def list_files(
        self, connection: Connection, prefix: str, page_token: str | None
    ) -> FileListing:
        # ponytail: a new client per request. Cache one per connection if listing latency matters.
        client = client_for(connection.credentials, connection.region)
        params = {
            "Bucket": connection.bucket,
            "Prefix": prefix,
            "Delimiter": "/",
            "MaxKeys": PAGE_SIZE,
        }
        if page_token:
            params["ContinuationToken"] = page_token
        with translated_errors(connection.bucket):
            page = client.list_objects_v2(**params)

        files = [
            S3File(obj["Key"], obj["Size"], obj["LastModified"], FileFormat.from_key(obj["Key"]))
            for obj in page.get("Contents", [])
            if not obj["Key"].endswith("/")  # zero-byte "folder" markers made by the S3 console
        ]
        folders = [common["Prefix"] for common in page.get("CommonPrefixes", [])]
        return FileListing(folders, files, page.get("NextContinuationToken"))


def client_for(credentials: S3Credentials, region: str):
    return boto3.client(
        "s3",
        region_name=region,
        aws_access_key_id=credentials.access_key_id,
        aws_secret_access_key=credentials.secret_access_key,
        config=_CONFIG,
    )


@contextmanager
def translated_errors(bucket: str):
    """Turn any botocore failure inside the block into a domain error, logging it once.

    Reading a response body can fail long after the request succeeded, so stream consumers wrap
    their whole read loop in this, not just the call that opened the object.
    """
    try:
        yield
    except (boto_errors.ClientError, boto_errors.BotoCoreError) as error:
        _log_failure(error, bucket)
        raise translate(error) from error


def _log_failure(error: Exception, bucket: str) -> None:
    """One line per failure for operators. Bucket names are not secret; keys never appear here."""
    if isinstance(error, boto_errors.ClientError):
        logger.warning(
            "S3 request failed: code=%s request_id=%s bucket=%s",
            error.response.get("Error", {}).get("Code"),
            error.response.get("ResponseMetadata", {}).get("RequestId"),
            bucket,
        )
    else:
        logger.warning("S3 unreachable: error=%s bucket=%s", type(error).__name__, bucket)


def open_object(connection: Connection, key: str, first_bytes: int | None = None):
    """Open an object for streaming: (body, total_size). `first_bytes` reads only a prefix."""
    client = client_for(connection.credentials, connection.region)
    params = {"Bucket": connection.bucket, "Key": key}
    if first_bytes:
        params["Range"] = f"bytes=0-{first_bytes - 1}"
    with translated_errors(connection.bucket):
        response = client.get_object(**params)
    # For a ranged read, ContentRange ("bytes 0-99/1234") carries the object's full size.
    content_range = response.get("ContentRange")
    size = int(content_range.rsplit("/", 1)[1]) if content_range else response["ContentLength"]
    return response["Body"], size


def read_first_lines(connection: Connection, key: str, max_bytes: int) -> bytes:
    """The start of an object, cut back to its last complete line. One ranged GET, any file size."""
    body, size = open_object(connection, key, first_bytes=max_bytes)
    with translated_errors(connection.bucket):
        head = body.read()
    if size > len(head):
        head = head[: head.rfind(b"\n") + 1]  # drop the line the cut went through
    return head
