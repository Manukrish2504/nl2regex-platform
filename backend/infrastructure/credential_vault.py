import json

from cryptography.fernet import Fernet, InvalidToken
from django.core.cache import caches

from domain.connections import Connection, S3Credentials


class EncryptedCredentialVault:
    """Holds connections Fernet-encrypted in a Django cache (Redis in production).

    Two clocks expire an entry: the cache TTL is a sliding idle timeout, refreshed on every load,
    and Fernet's own timestamp enforces an absolute maximum age that refreshing cannot extend.
    """

    # ponytail: single key. Swap Fernet for MultiFernet when key rotation is needed.
    def __init__(self, key: str, idle_ttl: int, max_age: int, cache_alias: str = "vault"):
        self._fernet = Fernet(key)
        self._idle_ttl = idle_ttl
        self._max_age = max_age
        self._cache_alias = cache_alias

    @property
    def _cache(self):
        return caches[self._cache_alias]

    def store(self, connection: Connection) -> None:
        payload = json.dumps(
            {
                "id": connection.id,
                "bucket": connection.bucket,
                "region": connection.region,
                "access_key_id": connection.credentials.access_key_id,
                "secret_access_key": connection.credentials.secret_access_key,
            }
        )
        ciphertext = self._fernet.encrypt(payload.encode()).decode()
        self._cache.set(_key(connection.id), ciphertext, self._idle_ttl)

    def load(self, connection_id: str) -> Connection | None:
        ciphertext = self._cache.get(_key(connection_id))
        if ciphertext is None:
            return None
        try:
            payload = json.loads(self._fernet.decrypt(ciphertext.encode(), ttl=self._max_age))
        except InvalidToken:  # tampered with, encrypted under another key, or past max_age
            self.delete(connection_id)
            return None
        # Fernet authenticates the ciphertext but not where it is stored. Checking the id inside
        # stops someone with Redis write access from copying one session's entry over another's.
        if payload["id"] != connection_id:
            return None

        self._cache.touch(_key(connection_id), self._idle_ttl)
        return Connection(
            id=payload["id"],
            bucket=payload["bucket"],
            region=payload["region"],
            credentials=S3Credentials(payload["access_key_id"], payload["secret_access_key"]),
        )

    def delete(self, connection_id: str) -> None:
        self._cache.delete(_key(connection_id))


def _key(connection_id: str) -> str:
    return f"connection:{connection_id}"
