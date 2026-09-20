# nl2regex-platform

Natural-language data transformation at scale. Connect your own S3 bucket, describe a pattern in plain
English, and an LLM-generated (and validated) regex is applied across millions of rows by PySpark,
asynchronously via Celery.

**Stack:** Django + DRF · React (Vite, TypeScript) · Celery · Redis · PySpark · Postgres

> Work in progress. So far: the one-command stack, and the S3 connection API with its credential
> vault. The UI, job pipeline, Spark engine, LLM integration, deployment URL and demo video land here
> as the build progresses.

## Run

```sh
docker compose up --build
```

| Service | URL |
|---|---|
| UI | http://localhost:5173 |
| API health | http://localhost:8000/api/health/ |
| Flower (worker monitoring) | http://localhost:5555 |

No `.env` is needed for local development; compose supplies dev-only defaults.

## Architecture

The backend is four layers. Dependencies only point inward, and
[a test](backend/tests/test_architecture.py) fails the build if an import breaks that rule.

```
presentation     api/             DRF views, serializers, error mapping. No logic.
                  │               (Celery tasks join this layer in the job pipeline.)
service          services/        Use-cases. Standard library and domain imports only.
                  │
domain           domain/          Entities, errors, and ports (interfaces). Standard library only.
                  ▲
infrastructure   infrastructure/  boto3 S3 adapter, encrypted credential vault, cache serializer.
```

- **The domain defines what it needs** as `typing.Protocol` ports (`ObjectStorage`,
  `CredentialVault`). Infrastructure implements them, so boto3, Redis and Django never leak into
  the business rules, and the service layer is tested with small in-memory fakes.
- **`config/container.py` is the composition root.** It is the one place that wires real adapters
  into services. Views, and later Celery tasks, ask it for a service and never import
  infrastructure themselves.
- **Errors are domain objects.** Each has a stable `code` and a message that is safe to show.
  One handler maps them to HTTP statuses, so every API failure has the same shape:
  `{"error": {"code": "...", "message": "..."}}`.

## How your AWS credentials are handled

You connect with your own access key, secret key and bucket name. This is what happens to them.

| Concern | What the app does |
|---|---|
| Validation | The keys are checked against S3 before anything is stored. A failed attempt stores nothing. |
| Storage | They are encrypted with Fernet (AES-128-CBC with an HMAC) and kept in Redis only. They are never written to Postgres or to disk by the app. The encryption key lives in the app's environment, so a Redis dump alone is useless. |
| Expiry | A connection is forgotten after 1 hour without use, and after 8 hours regardless. **Disconnect** deletes it at once. |
| API responses | No endpoint returns the keys. The connect response contains only the bucket name and its region. |
| Your browser's handle | A random token in an `HttpOnly`, `SameSite=Strict`, `Secure` cookie. It never appears in a URL or an access log, and JavaScript cannot read it. The server stores only the token's SHA-256, so leaked server data contains nothing a browser could replay. |
| Logs | Keys are never logged. The credentials object masks itself in `repr`, the AWS SDK loggers are pinned above the level at which they print request headers, and a failed connect logs only the AWS error code, request ID and bucket name. |
| Background jobs | Workers will receive a connection ID and look the keys up themselves. Keys are never passed as Celery task arguments, which Flower and the result backend would display. |
| Abuse | Connect attempts are rate limited per client, so the endpoint cannot be used to test stolen keys in bulk. The API accepts JSON only, which blocks cross-site form posts from connecting a visitor's browser to someone else's bucket. |

Errors are specific: wrong keys, a bucket that doesn't exist, keys without permission on the
bucket, and S3 being unreachable each produce their own message.

### Minimum IAM policy

The app only ever reads. This is all it needs, and it is what the project itself is tested with:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    { "Effect": "Allow", "Action": "s3:ListBucket", "Resource": "arn:aws:s3:::YOUR_BUCKET" },
    { "Effect": "Allow", "Action": "s3:GetObject", "Resource": "arn:aws:s3:::YOUR_BUCKET/*" }
  ]
}
```

The bucket can be in any region. The app discovers the region when you connect.

## Tests

```sh
cd backend
uv run pytest        # needs no Docker, database or AWS account
uv run ruff check .
```

Tests use in-memory caches and a fake S3 ([moto](https://github.com/getmoto/moto)), and the same
commands run in CI on every pull request.

`scripts/make_sample_data.py` generates a deterministic, deliberately messy customer dataset (CSV or
Excel, any row count) for demos and benchmarks.
