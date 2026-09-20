from unittest.mock import patch

import pytest
from rest_framework.test import APIClient

from infrastructure.celery_queue import CeleryTaskQueue
from tasks.files import build_preview
from tasks.jobs import run_job

pytestmark = pytest.mark.django_db
CSV = b"id,email\n" + b"".join(b"%d,user%d@example.com\n" % (n, n) for n in range(120))


def connect(s3_bucket):
    client = APIClient()
    body = {
        "access_key_id": "AKIAEXAMPLEEXAMPLE00",
        "secret_access_key": "wJalrXUtnFEMI-not-a-real-secret-EXAMPLEKEY",
        "bucket": s3_bucket,
    }
    assert client.post("/api/connection/", body, format="json").status_code == 201
    return client


@pytest.fixture
def client(s3_bucket, put_object):
    put_object("data.csv", CSV)
    return connect(s3_bucket)


@pytest.fixture
def queue():
    """Stands in for the broker, recording what would have been sent to workers."""
    with (
        patch.object(CeleryTaskQueue, "enqueue_job") as jobs,
        patch.object(CeleryTaskQueue, "enqueue_preview") as previews,
    ):
        yield {"jobs": jobs, "previews": previews}


def submit(client, **overrides):
    body = {
        "file_key": "data.csv",
        "pattern": r"\S+@\S+",
        "replacement": "REDACTED",
        "columns": ["email"],
    } | overrides
    return client.post("/api/jobs/", body, format="json")


def test_submit_answers_at_once_with_a_queued_job(client, queue):
    response = submit(client)

    assert response.status_code == 202
    job = response.json()
    assert (job["status"], job["progress"], job["error"]) == ("QUEUED", 0, None)
    queue["jobs"].assert_called_once_with(job["id"])  # handed to a worker, not run here
    assert "connection_id" not in job


def test_the_whole_lifecycle_over_the_api(client, queue):
    job_id = submit(client).json()["id"]
    assert client.get(f"/api/jobs/{job_id}/rows/").status_code == 409  # no results yet

    run_job.apply(args=[job_id])  # what a worker does with the queued message

    job = client.get(f"/api/jobs/{job_id}/").json()
    assert (job["status"], job["progress"], job["rows_total"], job["rows_changed"]) == (
        "SUCCESS",
        100,
        120,
        120,
    )
    page = client.get(f"/api/jobs/{job_id}/rows/", {"page": 3, "page_size": 50}).json()
    assert (page["columns"], page["page"], page["page_size"], page["total_rows"]) == (
        ["id", "email"],
        3,
        50,
        120,
    )
    assert len(page["rows"]) == 20
    assert page["rows"][0] == ["100", "REDACTED"]
    assert [listed["id"] for listed in client.get("/api/jobs/").json()["jobs"]] == [job_id]


def test_cancelling_a_queued_job(client, queue):
    job_id = submit(client).json()["id"]
    assert client.post(f"/api/jobs/{job_id}/cancel/").json()["status"] == "CANCELLED"

    run_job.apply(args=[job_id])  # the message is still in the queue, and must now do nothing
    assert client.get(f"/api/jobs/{job_id}/").json()["status"] == "CANCELLED"


def test_a_failed_job_carries_a_message_the_user_can_act_on(client, queue):
    job_id = submit(client, columns=["emial"]).json()["id"]
    run_job.apply(args=[job_id])
    assert client.get(f"/api/jobs/{job_id}/").json()["error"] == {
        "code": "column_not_found",
        "message": "The file has no column named 'emial'.",
    }


def test_jobs_are_invisible_to_other_connections(client, queue, s3_bucket):
    job_id = submit(client).json()["id"]
    stranger = connect(s3_bucket)

    assert stranger.get("/api/jobs/").json() == {"jobs": []}
    for response in (
        stranger.get(f"/api/jobs/{job_id}/"),
        stranger.post(f"/api/jobs/{job_id}/cancel/"),
        stranger.get(f"/api/jobs/{job_id}/rows/"),
    ):
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "job_not_found"


def test_every_job_endpoint_needs_a_connection(queue):
    anonymous = APIClient()
    job_id = "11111111-1111-4111-8111-111111111111"
    for response in (
        anonymous.get("/api/jobs/"),
        submit(anonymous),
        anonymous.get(f"/api/jobs/{job_id}/"),
        anonymous.post(f"/api/jobs/{job_id}/cancel/"),
        anonymous.get(f"/api/jobs/{job_id}/rows/"),
        anonymous.get("/api/connection/files/preview/", {"key": "data.csv"}),
    ):
        assert response.status_code == 401


@pytest.mark.parametrize(
    ("overrides", "code"),
    [
        ({"pattern": "(unclosed"}, "invalid_pattern"),
        ({"file_key": "notes.txt"}, "unsupported_file"),
        ({"pattern": ""}, "validation_error"),
        ({"pattern": "x" * 1001}, "validation_error"),
        ({"columns": "email"}, "validation_error"),
    ],
)
def test_bad_submissions_are_rejected_and_nothing_is_queued(client, queue, overrides, code):
    response = submit(client, **overrides)
    assert response.status_code == 400
    assert response.json()["error"]["code"] == code
    queue["jobs"].assert_not_called()


@pytest.mark.parametrize("query", [{"page": 0}, {"page_size": 201}, {"page": "two"}])
def test_page_parameters_are_validated(client, queue, query):
    job_id = submit(client).json()["id"]
    run_job.apply(args=[job_id])
    assert client.get(f"/api/jobs/{job_id}/rows/", query).status_code == 400


def test_a_fourth_active_job_is_refused(client, queue):
    assert [submit(client).status_code for _ in range(4)] == [202, 202, 202, 429]


def test_disconnecting_forgets_jobs_and_their_output(client, queue, settings):
    job_id = submit(client).json()["id"]
    run_job.apply(args=[job_id])
    assert list(settings.RESULTS_DIR.iterdir()) != []

    assert client.delete("/api/connection/").status_code == 204
    assert list(settings.RESULTS_DIR.iterdir()) == []
    assert client.get(f"/api/jobs/{job_id}/").status_code == 401


def test_file_preview_is_polled_until_the_worker_has_read_the_file(client, queue):
    url, query = "/api/connection/files/preview/", {"key": "data.csv"}
    assert client.get(url, query).json() == {"status": "pending"}
    assert client.get(url, query).json() == {"status": "pending"}
    queue["previews"].assert_called_once()

    build_preview.apply(args=list(queue["previews"].call_args.args))
    preview = client.get(url, query).json()
    assert (preview["status"], preview["columns"]) == ("done", ["id", "email"])
    assert preview["rows"][0] == ["0", "user0@example.com"]

    assert client.get(url, {"key": "notes.txt"}).status_code == 400
    assert client.get(url).status_code == 400
