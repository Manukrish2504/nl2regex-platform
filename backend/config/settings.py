"""Django settings. All environment-specific values come from env vars (see docker-compose.yml)."""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.environ["DJANGO_SECRET_KEY"]
DEBUG = os.environ.get("DJANGO_DEBUG") == "1"
ALLOWED_HOSTS = os.environ.get("DJANGO_ALLOWED_HOSTS", "localhost").split(",")

# No user accounts: a session is identified by an S3 connection, not a login,
# so auth/admin/sessions are deliberately left out.
INSTALLED_APPS = [
    "rest_framework",
    "api",
    "infrastructure",  # only so Django manages its tables; see infrastructure/models.py
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.middleware.common.CommonMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "HOST": os.environ.get("POSTGRES_HOST", "localhost"),
        "NAME": os.environ.get("POSTGRES_DB", "nl2regex"),
        "USER": os.environ.get("POSTGRES_USER", "nl2regex"),
        "PASSWORD": os.environ.get("POSTGRES_PASSWORD", ""),
    }
}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# One Redis, four logical databases: broker, task results, application cache, credential vault.
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379")
CELERY_BROKER_URL = f"{REDIS_URL}/0"
CELERY_RESULT_BACKEND = f"{REDIS_URL}/1"
CELERY_IMPORTS = ("tasks.jobs", "tasks.files")
# Jobs have a queue of their own. How many run at once is then a capacity decision (how many
# Spark applications the cluster can hold), and a file preview never waits behind a long job.
CELERY_TASK_ROUTES = {"tasks.jobs.run_job": {"queue": "jobs"}}

# Jobs are long, so a worker must not reserve more messages than it is running.
CELERY_WORKER_PREFETCH_MULTIPLIER = 1
# Acknowledge a message only after its task ends. If the worker process dies first, the broker
# hands the message out again, and the job is taken over instead of being lost.
CELERY_TASK_ACKS_LATE = True
CELERY_TASK_REJECT_ON_WORKER_LOST = True
# The soft limit raises inside the task, which then fails its job cleanly. The hard limit kills
# the process for code that cannot be interrupted, such as a runaway regex match.
CELERY_TASK_SOFT_TIME_LIMIT = 15 * 60
CELERY_TASK_TIME_LIMIT = 16 * 60
# Redis hands out again any message left unacknowledged for this long. It must exceed the hard
# limit, or a long job would be started twice. It is also how long a job waits to be taken over
# when a whole worker dies (one dead process is noticed at once), so it stays close to the limit
# instead of at Redis's 1-hour default.
CELERY_BROKER_TRANSPORT_OPTIONS = {"visibility_timeout": CELERY_TASK_TIME_LIMIT + 4 * 60}

JOB_MAX_ACTIVE_PER_CONNECTION = 3
JOB_MAX_ATTEMPTS = 3
# A job still RUNNING after this long has no worker left: the hard limit killed it, and that
# message was acknowledged, so nothing will redeliver it. This must exceed the visibility timeout,
# or it would fail a job that is about to be taken over.
JOB_STALE_AFTER = CELERY_BROKER_TRANSPORT_OPTIONS["visibility_timeout"] + 2 * 60
# Job output (Parquet). Web and workers must see the same folder: a shared volume in compose.
RESULTS_DIR = Path(os.environ.get("RESULTS_DIR", BASE_DIR / ".results"))

# "spark" is the engine. "streaming" is the single-process reference implementation the Spark
# engine is tested against; it needs no JVM, so it doubles as a fallback.
TRANSFORM_ENGINE = os.environ.get("TRANSFORM_ENGINE", "spark")
SPARK_MASTER_URL = os.environ.get("SPARK_MASTER_URL", "local[2]")
SPARK_CONF = {
    "spark.driver.memory": os.environ.get("SPARK_DRIVER_MEMORY", "1g"),
    "spark.executor.memory": os.environ.get("SPARK_EXECUTOR_MEMORY", "1g"),
}
# The cores one job may take from the cluster. Unset, a job takes every free core, which suits
# one job at a time. With N jobs at once, give each a share: the cluster's cores divided by N.
if os.environ.get("SPARK_CORES_MAX"):
    SPARK_CONF["spark.cores.max"] = os.environ["SPARK_CORES_MAX"]
# Turns a plain-English request into a pattern. Without a key that mode is switched off and the
# rest of the application works as before. The model was chosen by scripts/eval_prompts.py.
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
LLM_MODEL = os.environ.get("LLM_MODEL", "claude-opus-5")
LLM_TIMEOUT = float(os.environ.get("LLM_TIMEOUT", "20"))
PATTERN_CACHE_TTL = 30 * 24 * 60 * 60

# boto3 reads this variable by itself; Spark's S3 connector has to be told. Only set for
# S3-compatible stores and local fakes, never for AWS.
S3_ENDPOINT_URL = os.environ.get("AWS_ENDPOINT_URL_S3")


def _redis_cache(database: int) -> dict:
    return {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": f"{REDIS_URL}/{database}",
        # Django's default serializer unpickles whatever is in Redis. JSON cannot execute code.
        "OPTIONS": {"serializer": "infrastructure.caching.JSONSerializer"},
    }


CACHES = {"default": _redis_cache(2), "vault": _redis_cache(3)}

# User-supplied AWS credentials are encrypted with this key before they reach Redis.
CREDENTIAL_ENCRYPTION_KEY = os.environ["CREDENTIAL_ENCRYPTION_KEY"]
CONNECTION_IDLE_TTL = 60 * 60  # seconds without use before a connection is forgotten
CONNECTION_MAX_AGE = 8 * 60 * 60  # hard ceiling, however active the connection is

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [],
    "DEFAULT_PERMISSION_CLASSES": [],
    "UNAUTHENTICATED_USER": None,
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    # JSON only. A browser can send an HTML form cross-site without a preflight, and the response
    # may set a SameSite=Strict cookie, which would let another site connect a visitor to the
    # attacker's bucket. A form post now gets a 415.
    "DEFAULT_PARSER_CLASSES": ["rest_framework.parsers.JSONParser"],
    "DEFAULT_THROTTLE_RATES": {"connect": "10/min", "jobs": "30/min"},
    # Throttles identify clients by IP. Behind the reverse proxy that is the last
    # X-Forwarded-For entry, which the proxy sets and a client cannot forge.
    "NUM_PROXIES": 1,
    "EXCEPTION_HANDLER": "api.exception_handler.handle",
}

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"plain": {"format": "{levelname} {name}: {message}", "style": "{"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "plain"}},
    "root": {"handlers": ["console"], "level": "INFO"},
    "loggers": {
        # At DEBUG these print request headers, which include the access key ID. They stay at
        # WARNING whatever the root level is.
        "boto3": {"level": "WARNING"},
        "botocore": {"level": "WARNING"},
        "urllib3": {"level": "WARNING"},
        # The Python-to-JVM bridge. At DEBUG it prints every call it relays, and the calls that
        # configure a Spark session carry the keys.
        "py4j": {"level": "WARNING"},
        # The same rule for the Anthropic SDK and the HTTP client under it, whose debug output
        # includes request headers.
        "anthropic": {"level": "WARNING"},
        "httpx": {"level": "WARNING"},
        "httpx2": {"level": "WARNING"},
        "httpcore": {"level": "WARNING"},
    },
}

TIME_ZONE = "UTC"
USE_TZ = True
