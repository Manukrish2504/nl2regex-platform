#!/usr/bin/env bash
# Writes the .env this Codespace needs, then builds the production stack. Run once, when the
# Codespace is created; docker compose up happens on every start.
set -euo pipefail
cd "$(dirname "$0")/.."

# A Fernet key is 32 random bytes, url-safe base64. Generating it here avoids installing
# cryptography just to call Fernet.generate_key().
random() { python3 -c "import base64, os; print(base64.urlsafe_b64encode(os.urandom($1)).decode().rstrip('='))"; }
fernet() { python3 -c "import base64, os; print(base64.urlsafe_b64encode(os.urandom(32)).decode())"; }

if [ -f .env ]; then
  echo "Keeping the .env that is already here."
else
  # The browser reaches this Codespace over HTTPS that Codespaces terminates, so Caddy serves
  # plain HTTP on 80 and asks no certificate authority for anything. ":80" is Caddy's way of
  # saying "this port, any hostname", which is what a forwarding domain needs.
  {
    echo "# Written by .devcontainer/setup.sh. Throwaway, and never committed."
    echo "SITE_HOST=:80"
    echo "DJANGO_ALLOWED_HOSTS=${CODESPACE_NAME:-localhost}-80.${GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN:-app.github.dev},localhost"
    echo "DJANGO_SECRET_KEY=$(random 64)"
    echo "CREDENTIAL_ENCRYPTION_KEY=$(fernet)"
    echo "POSTGRES_PASSWORD=$(random 32)"
    echo "SPARK_AUTH_SECRET=$(random 32)"
    echo "FLOWER_BASIC_AUTH=flower:$(random 12)"
    echo ""
    echo "# Sized for a 4-core, 16 GB Codespace: one Spark worker with two cores, which leaves"
    echo "# room for the driver, gunicorn and Postgres to run at the same time."
    echo "SPARK_WORKERS=1"
    echo "SPARK_WORKER_CORES=2"
    echo "SPARK_WORKER_MEMORY=3g"
    echo "SPARK_EXECUTOR_MEMORY=2g"
    echo "WEB_WORKERS=2"
    echo "JOB_CONCURRENCY=1"
  } > .env
  echo "Wrote .env. ANTHROPIC_API_KEY is deliberately not in it: set it as a Codespaces secret"
  echo "and Compose will read it from the environment, where it stays out of the file system."
fi

# About 15 minutes the first time: PySpark, a Java runtime and Spark's S3 connector jars.
docker compose -f docker-compose.prod.yml build
