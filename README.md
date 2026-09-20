# nl2regex-platform

Natural-language data transformation at scale. Connect your own S3 bucket, describe a pattern in plain
English, and an LLM-generated (and validated) regex is applied across millions of rows by PySpark,
asynchronously via Celery.

**Stack:** Django + DRF · React (Vite, TypeScript) · Celery · Redis · PySpark · Postgres

> Work in progress. Architecture notes, partitioning rationale, deployment URL and demo video land here
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
