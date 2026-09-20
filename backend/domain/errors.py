"""Failures the user can act on. Each has a stable `code` and a message that is safe to display."""


class DomainError(Exception):
    code = "error"
    message = "Something went wrong."

    def __init__(self, message: str | None = None):
        if message:
            self.message = message
        super().__init__(self.message)


class InvalidCredentials(DomainError):
    code = "invalid_credentials"
    message = "AWS rejected these credentials. Check the access key and secret key."


class BucketNotFound(DomainError):
    code = "bucket_not_found"
    message = "No bucket with that name exists."


class BucketAccessDenied(DomainError):
    code = "bucket_access_denied"
    message = "These credentials are valid but cannot list this bucket. It needs s3:ListBucket."


class StorageUnreachable(DomainError):
    code = "storage_unreachable"
    message = "Could not reach Amazon S3. Try again in a moment."


class StorageError(DomainError):
    """An AWS failure with no specific handling. Carries the AWS code so it can be reported."""

    code = "storage_error"

    def __init__(self, aws_code: str):
        super().__init__(f"Amazon S3 returned an unexpected error ({aws_code}).")


class InvalidPageToken(DomainError):
    code = "invalid_page_token"
    message = "That page of results is no longer available. Reload the file list."


class ConnectionNotFound(DomainError):
    code = "connection_not_found"
    message = "Your S3 connection has expired. Connect again to continue."
