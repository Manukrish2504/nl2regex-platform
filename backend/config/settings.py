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
    "DEFAULT_THROTTLE_RATES": {"connect": "10/min"},
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
    },
}

TIME_ZONE = "UTC"
USE_TZ = True
