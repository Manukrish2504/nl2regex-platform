import pytest

from domain.connections import FileListing, S3Credentials
from domain.errors import ConnectionNotFound, InvalidCredentials
from services.connections import ConnectionService, connection_id_for

CREDENTIALS = S3Credentials("AKIAEXAMPLEEXAMPLE00", "not-a-real-secret-key")


class FakeStorage:
    def __init__(self, error=None):
        self.error = error

    def resolve_bucket(self, credentials, bucket):
        if self.error:
            raise self.error
        return "eu-north-1"

    def list_files(self, connection, prefix, page_token):
        return FileListing([f"{connection.bucket}/{prefix}"], [], None)


class FakeVault:
    def __init__(self):
        self.entries = {}

    def store(self, connection):
        self.entries[connection.id] = connection

    def load(self, connection_id):
        return self.entries.get(connection_id)

    def delete(self, connection_id):
        self.entries.pop(connection_id, None)


def test_connect_stores_the_connection_under_a_digest_of_the_token():
    vault = FakeVault()
    token, connection = ConnectionService(FakeStorage(), vault).connect(CREDENTIALS, "my-bucket")

    assert connection.region == "eu-north-1"
    assert list(vault.entries) == [connection_id_for(token)]
    assert token not in vault.entries  # the raw token is never a key


def test_failed_validation_stores_nothing_and_keeps_the_previous_connection():
    vault = FakeVault()
    old_token, _ = ConnectionService(FakeStorage(), vault).connect(CREDENTIALS, "old-bucket")

    failing = ConnectionService(FakeStorage(error=InvalidCredentials()), vault)
    with pytest.raises(InvalidCredentials):
        failing.connect(CREDENTIALS, "new-bucket", previous_token=old_token)

    assert list(vault.entries) == [connection_id_for(old_token)]


def test_reconnecting_replaces_the_previous_connection():
    vault = FakeVault()
    service = ConnectionService(FakeStorage(), vault)
    old_token, _ = service.connect(CREDENTIALS, "old-bucket")
    new_token, _ = service.connect(CREDENTIALS, "new-bucket", previous_token=old_token)

    assert list(vault.entries) == [connection_id_for(new_token)]


@pytest.mark.parametrize("token", [None, "", "unknown-token"])
def test_unknown_or_missing_token_is_not_found(token):
    service = ConnectionService(FakeStorage(), FakeVault())
    with pytest.raises(ConnectionNotFound):
        service.get(token)
    with pytest.raises(ConnectionNotFound):
        service.list_files(token, "", None)


def test_list_files_uses_the_stored_connection():
    service = ConnectionService(FakeStorage(), FakeVault())
    token, _ = service.connect(CREDENTIALS, "my-bucket")
    assert service.list_files(token, "samples/", None).folders == ["my-bucket/samples/"]


def test_disconnect_forgets_the_connection():
    service = ConnectionService(FakeStorage(), FakeVault())
    token, _ = service.connect(CREDENTIALS, "my-bucket")
    service.disconnect(token)
    with pytest.raises(ConnectionNotFound):
        service.get(token)


def test_credentials_repr_never_shows_the_secret():
    text = f"{CREDENTIALS!r} {CREDENTIALS}"
    assert CREDENTIALS.secret_access_key not in text
    assert CREDENTIALS.access_key_id not in text
