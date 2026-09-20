import boto3
import pytest
from django.conf import settings
from django.core.cache import caches
from moto import mock_aws

BUCKET = "demo-bucket"
REGION = "eu-north-1"  # deliberately not the adapter's discovery region


@pytest.fixture(autouse=True)
def _empty_caches():
    """Vault entries and throttle counters must not leak from one test into the next."""
    for alias in settings.CACHES:
        caches[alias].clear()


@pytest.fixture(autouse=True)
def _isolated_services(settings, tmp_path):
    """Each test gets its own results folder and freshly wired services."""
    from config import container

    settings.RESULTS_DIR = tmp_path / "results"
    for factory in (container.connection_service, container.job_service, container.preview_service):
        factory.cache_clear()


@pytest.fixture
def s3_bucket():
    """A fake S3 (moto) holding a small bucket. Yields the bucket name."""
    with mock_aws():
        client = boto3.client(
            "s3", region_name=REGION, aws_access_key_id="testing", aws_secret_access_key="testing"
        )
        client.create_bucket(
            Bucket=BUCKET, CreateBucketConfiguration={"LocationConstraint": REGION}
        )
        for key in (
            "readme.txt",
            "samples/",  # the zero-byte marker the S3 console creates for a "folder"
            "samples/customers.csv",
            "samples/REPORT.XLSX",
            "samples/notes.txt",
            "samples/archive/old.csv",
        ):
            client.put_object(Bucket=BUCKET, Key=key, Body=b"" if key.endswith("/") else b"data")
        yield BUCKET


@pytest.fixture
def put_object(s3_bucket):
    """Upload a file into the fake bucket: put_object("data/x.csv", b"id,name\\n1,A\\n")."""
    client = boto3.client(
        "s3", region_name=REGION, aws_access_key_id="testing", aws_secret_access_key="testing"
    )

    def put(key: str, body: bytes) -> str:
        client.put_object(Bucket=BUCKET, Key=key, Body=body)
        return key

    return put


@pytest.fixture
def connection(s3_bucket):
    """A domain Connection pointing at the fake bucket."""
    from domain.connections import Connection, S3Credentials

    return Connection(
        "a" * 64, BUCKET, REGION, S3Credentials("AKIAEXAMPLEEXAMPLE00", "not-a-secret")
    )
