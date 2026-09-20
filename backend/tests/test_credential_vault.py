import time

import pytest
from cryptography.fernet import Fernet
from django.core.cache import caches

from domain.connections import Connection, S3Credentials
from infrastructure.credential_vault import EncryptedCredentialVault

SECRET = "wJalrXUtnFEMI-not-a-real-secret-EXAMPLEKEY"
HOUR = 60 * 60


def _connection(connection_id="a" * 64):
    return Connection(
        connection_id, "my-bucket", "eu-north-1", S3Credentials("AKIAEXAMPLEEXAMPLE00", SECRET)
    )


@pytest.fixture
def vault():
    return EncryptedCredentialVault(Fernet.generate_key().decode(), idle_ttl=HOUR, max_age=8 * HOUR)


def _raw(connection_id):
    return caches["vault"].get(f"connection:{connection_id}")


def test_round_trip(vault):
    vault.store(_connection())
    assert vault.load("a" * 64) == _connection()


def test_what_is_stored_is_ciphertext(vault):
    vault.store(_connection())
    stored = _raw("a" * 64)
    assert SECRET not in stored
    assert "AKIAEXAMPLEEXAMPLE00" not in stored
    assert "my-bucket" not in stored


def test_unknown_id_is_missing(vault):
    assert vault.load("f" * 64) is None


def test_tampered_ciphertext_is_missing(vault):
    vault.store(_connection())
    stored = _raw("a" * 64)
    caches["vault"].set(f"connection:{'a' * 64}", stored[:-4] + "AAAA")
    assert vault.load("a" * 64) is None


def test_ciphertext_copied_from_another_session_is_missing(vault):
    vault.store(_connection("a" * 64))
    vault.store(_connection("b" * 64))
    caches["vault"].set(f"connection:{'b' * 64}", _raw("a" * 64))

    assert vault.load("b" * 64) is None
    assert vault.load("a" * 64) is not None


def test_ciphertext_from_another_key_is_missing(vault):
    other = EncryptedCredentialVault(Fernet.generate_key().decode(), idle_ttl=HOUR, max_age=HOUR)
    other.store(_connection())
    assert vault.load("a" * 64) is None


def test_max_age_applies_even_to_a_connection_in_constant_use(monkeypatch):
    # The idle timeout is longer than max_age here, so only the absolute cap can expire the entry.
    vault = EncryptedCredentialVault(
        Fernet.generate_key().decode(), idle_ttl=24 * HOUR, max_age=8 * HOUR
    )
    vault.store(_connection())
    now = time.time()

    monkeypatch.setattr(time, "time", lambda: now + 7 * HOUR)
    assert vault.load("a" * 64) is not None

    monkeypatch.setattr(time, "time", lambda: now + 9 * HOUR)
    assert vault.load("a" * 64) is None


def test_delete(vault):
    vault.store(_connection())
    vault.delete("a" * 64)
    assert vault.load("a" * 64) is None
