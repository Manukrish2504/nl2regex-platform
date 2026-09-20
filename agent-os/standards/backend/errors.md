# Domain Errors

A failure the user can act on is a domain object, never a library exception that
escaped.

```python
class BucketAccessDenied(DomainError):
    code = "bucket_access_denied"
    message = "These credentials are valid but cannot list this bucket. It needs s3:ListBucket."
```

- `code` is stable and machine-readable. `message` is safe to show a user as it is.
- **Translate once, at the adapter.** `s3_storage.translate()` maps every botocore
  failure; `spark_engine._translate()` maps Java failures by marker. Above the
  adapter, only domain errors travel.
- An unmapped failure keeps its provider code (`StorageError(aws_code)`) rather
  than pretending to be something known.
- Transient failures are a tuple the job service checks
  (`StorageUnreachable`, `EngineUnavailable`, `LLMUnavailable`); everything else
  fails the job at once. Getting this wrong means retrying a bad password 3 times.

`api/exception_handler.py` maps error types to HTTP statuses in one dict, so every
API failure has the shape `{"error": {"code", "message"}}`.
