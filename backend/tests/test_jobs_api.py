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


# --- a job described in plain English ------------------------------------------------------


@pytest.fixture
def language_model(settings):
    """A server with an API key, and a stand-in for the model behind it."""
    from fakes import FakeWriter

    from config import container
    from domain.patterns import PatternSuggestion

    settings.ANTHROPIC_API_KEY = "sk-ant-test"
    writer = FakeWriter(
        PatternSuggestion(
            pattern=r"\S+@\S+",
            explanation="Matches e-mail addresses.",
            replacement="REDACTED",
            columns=["Email"],
            should_match=["a@x.com"],
            should_not_match=["nothing"],
        )
    )
    container.pattern_service.cache_clear()
    container.job_service.cache_clear()
    with patch("infrastructure.claude_pattern_writer.ClaudePatternWriter", return_value=writer):
        yield writer


def test_the_config_endpoint_says_whether_prompts_can_be_used(client, settings):
    assert client.get("/api/config/").json() == {"describe_available": False}


def test_the_config_endpoint_with_a_key(client, language_model):
    assert client.get("/api/config/").json() == {"describe_available": True}


def test_a_prompt_alone_is_queued_and_the_model_is_not_called_by_the_request(
    client, queue, language_model
):
    body = {"file_key": "data.csv", "prompt": "Find email addresses in the Email column."}
    response = client.post("/api/jobs/", body, format="json")

    assert response.status_code == 202
    job = response.json()
    assert (job["prompt"], job["pattern"], job["pattern_source"]) == (body["prompt"], "", "llm")
    assert job["explanation"] is None
    assert language_model.calls == []


def test_a_worker_fills_in_the_pattern_and_the_api_shows_where_it_came_from(
    client, queue, language_model
):
    body = {"file_key": "data.csv", "prompt": "Find email addresses in the Email column."}
    job_id = client.post("/api/jobs/", body, format="json").json()["id"]
    run_job.apply(args=[job_id])

    job = client.get(f"/api/jobs/{job_id}/").json()
    assert (job["status"], job["pattern"], job["pattern_source"]) == ("SUCCESS", r"\S+@\S+", "llm")
    assert job["explanation"] == "Matches e-mail addresses."
    # "the Email column" found the file's `email` column, and the stated replacement was used.
    assert (job["columns"], job["replacement"]) == (["Email"], "REDACTED")
    rows = client.get(f"/api/jobs/{job_id}/rows/").json()["rows"]
    assert rows[0] == ["0", "REDACTED"]


@pytest.mark.parametrize(
    "body",
    [
        {"file_key": "data.csv"},
        {"file_key": "data.csv", "pattern": "a", "prompt": "find the letter a"},
        {"file_key": "data.csv", "prompt": "ab"},
        {"file_key": "data.csv", "prompt": "x" * 501},
    ],
)
def test_a_job_needs_exactly_one_of_pattern_and_prompt(client, queue, language_model, body):
    assert client.post("/api/jobs/", body, format="json").status_code == 400


def test_a_prompt_is_refused_when_the_server_has_no_api_key(client, queue):
    body = {"file_key": "data.csv", "prompt": "find email addresses"}
    response = client.post("/api/jobs/", body, format="json")

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "llm_not_configured"
    queue["jobs"].assert_not_called()


# --- the transformations a language model plans ----------------------------------------------


@pytest.mark.parametrize(
    "body",
    [
        {"kind": "redact_pii", "pattern": "a"},
        {"kind": "redact_pii", "prompt": "mask everything"},
        {"kind": "standardise", "columns": []},
        {"kind": "standardise", "columns": ["id", "email"]},
        {"kind": "standardise", "columns": ["email"], "pattern": "a"},
        {"kind": "translate", "columns": ["email"]},
    ],
)
def test_each_kind_of_job_validates_its_own_fields(client, queue, language_model, body):
    response = client.post("/api/jobs/", {"file_key": "data.csv"} | body, format="json")
    assert response.status_code == 400


def test_a_redaction_job_runs_end_to_end_and_the_api_shows_its_report(
    client, queue, language_model
):
    from domain.advice import Finding

    finding = Finding("email", "email", "its shapes are e-mail addresses")
    with patch(
        "infrastructure.claude_data_advisers.ClaudePiiClassifier.classify", return_value=[finding]
    ) as classify:
        body = {"file_key": "data.csv", "kind": "redact_pii"}
        job_id = client.post("/api/jobs/", body, format="json").json()["id"]
        run_job.apply(args=[job_id])

    job = client.get(f"/api/jobs/{job_id}/").json()
    assert (job["status"], job["kind"], job["rows_changed"]) == ("SUCCESS", "redact_pii", 120)
    assert job["report"]["operations"] == [
        {"kind": "email", "placeholder": "[EMAIL]", "columns": ["email"], "rows_changed": 120}
    ]
    assert client.get(f"/api/jobs/{job_id}/rows/").json()["rows"][0] == ["0", "[EMAIL]"]
    # What the model was shown: shapes. The file's addresses are user0@example.com and so on.
    (profiles,) = classify.call_args.args
    assert "user" not in str(profiles) and "aaaa99@aaaaaaa.aaa" in str(profiles)


def test_a_standardise_job_runs_end_to_end(client, queue, language_model, put_object):
    put_object("places.csv", b"id,country\n1,USA\n2,us\n3,Germany\n4,us\n")
    with patch(
        "infrastructure.claude_data_advisers.ClaudeValueStandardiser.standardise",
        return_value=[("us", "USA")],
    ):
        body = {"file_key": "places.csv", "kind": "standardise", "columns": ["Country"]}
        job_id = client.post("/api/jobs/", body, format="json").json()["id"]
        run_job.apply(args=[job_id])

    job = client.get(f"/api/jobs/{job_id}/").json()
    assert (job["status"], job["rows_changed"]) == ("SUCCESS", 2)
    assert job["report"]["mapping"] == [{"from": "us", "to": "USA", "rows": 2}]
    rows = client.get(f"/api/jobs/{job_id}/rows/").json()["rows"]
    assert [row[1] for row in rows] == ["USA", "USA", "Germany", "USA"]
