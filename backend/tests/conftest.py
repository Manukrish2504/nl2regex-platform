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
