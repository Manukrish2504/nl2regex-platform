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


class EngineUnavailable(DomainError):
    code = "engine_unavailable"
    message = "The processing cluster could not be reached. Try again in a moment."


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


class UnsupportedFile(DomainError):
    code = "unsupported_file"
    message = "Only CSV and Excel (.xlsx) files can be processed."


class ObjectNotFound(DomainError):
    code = "file_not_found"
    message = "That file no longer exists in the bucket."


class FileUnreadable(DomainError):
    code = "file_unreadable"
    message = "The file could not be read."


class FileTooLarge(DomainError):
    code = "file_too_large"
    message = "This Excel file is too large to process."


class ColumnNotFound(DomainError):
    code = "column_not_found"

    def __init__(self, missing: list[str]):
        super().__init__(
            f"The file has no column named {', '.join(repr(name) for name in missing)}."
        )


class InvalidPattern(DomainError):
    code = "invalid_pattern"

    def __init__(self, reason: str):
        super().__init__(f"That is not a valid regular expression: {reason}.")


class TooManyActiveJobs(DomainError):
    code = "too_many_active_jobs"
    message = "You already have several jobs in progress. Wait for one to finish, or cancel one."


class JobNotFound(DomainError):
    code = "job_not_found"
    message = "No such job."


class JobNotFinished(DomainError):
    code = "job_not_finished"
    message = "This job has no results yet."


class ResultsExpired(DomainError):
    code = "results_expired"
    message = "The results of this job have been deleted. Run it again to see them."


class InvalidTransition(DomainError):
    code = "invalid_transition"
