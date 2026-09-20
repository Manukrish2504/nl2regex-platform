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
    InvalidCredentials,
    InvalidPageToken,
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
}


def translate(error: Exception) -> DomainError:
    """Map any botocore failure to a domain error. Unknown failures keep their AWS code."""
    if isinstance(error, boto_errors.ClientError):
        aws_code = error.response.get("Error", {}).get("Code", "Unknown")
        domain_error = _ERRORS_BY_AWS_CODE.get(aws_code)
        return domain_error() if domain_error else StorageError(aws_code)
    if isinstance(error, (boto_errors.ConnectionError, boto_errors.HTTPClientError)):
        return StorageUnreachable()
    return StorageError(type(error).__name__)


class S3Storage:
    def resolve_bucket(self, credentials: S3Credentials, bucket: str) -> str:
        client = _client(credentials, _DISCOVERY_REGION)
        with _translated_errors(bucket):
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
        client = _client(connection.credentials, connection.region)
        params = {
            "Bucket": connection.bucket,
            "Prefix": prefix,
            "Delimiter": "/",
            "MaxKeys": PAGE_SIZE,
        }
        if page_token:
            params["ContinuationToken"] = page_token
        with _translated_errors(connection.bucket):
            page = client.list_objects_v2(**params)

        files = [
            S3File(obj["Key"], obj["Size"], obj["LastModified"], FileFormat.from_key(obj["Key"]))
            for obj in page.get("Contents", [])
            if not obj["Key"].endswith("/")  # zero-byte "folder" markers made by the S3 console
        ]
        folders = [common["Prefix"] for common in page.get("CommonPrefixes", [])]
        return FileListing(folders, files, page.get("NextContinuationToken"))


def _client(credentials: S3Credentials, region: str):
    return boto3.client(
        "s3",
        region_name=region,
        aws_access_key_id=credentials.access_key_id,
        aws_secret_access_key=credentials.secret_access_key,
        config=_CONFIG,
    )


@contextmanager
def _translated_errors(bucket: str):
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
