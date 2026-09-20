"""Settings for the test suite: no Redis, Postgres or real secrets required."""

import os

from cryptography.fernet import Fernet

# Must be set before the real settings are imported, because they read these at import time.
os.environ.setdefault("DJANGO_SECRET_KEY", "test-only")
os.environ.setdefault("CREDENTIAL_ENCRYPTION_KEY", Fernet.generate_key().decode())

from .settings import *  # noqa: E402, F403

# ponytail: SQLite for tests, Postgres in compose. The repository uses only portable SQL
# (single-statement UPDATE ... WHERE), so nothing here depends on the difference.
DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}}

CACHES = {
    alias: {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": alias}
    for alias in ("default", "vault")
}
