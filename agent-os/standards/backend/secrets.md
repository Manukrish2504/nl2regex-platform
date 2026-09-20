# Secrets

The user's AWS keys and the server's API key never appear in a log, a response, a
task argument or a database row.

- **Encrypted at rest, in Redis only** (Fernet, `infrastructure/credential_vault.py`).
  Never in Postgres, never on disk.
- **The browser holds a token; the server stores its SHA-256.** Leaked server data
  contains nothing a browser could replay.
- **Celery tasks carry IDs only.** Flower and the result backend display arguments.
  A worker looks credentials up by connection ID.
- **`__repr__` masks itself** (`S3Credentials`), so a stray f-string cannot leak.
- **Pin every library logger that prints request headers** at WARNING:
  `boto3`, `botocore`, `urllib3`, `py4j`, `anthropic`, `httpx`, `httpcore`.
- **Set Spark's S3 credentials on the session at runtime**, never in `SparkConf`, a
  command line or an event log, and pin the provider to
  `SimpleAWSCredentialsProvider` so an empty key cannot fall back to the machine's
  own identity.
- **A failed call logs the code, the request ID and the bucket. Never the payload.**

Verify by counting, never by printing: `grep -c` the key in container logs, every
Redis database and a `pg_dump`, and assert zero.
