"""The Claude adapter, with the network replaced at the wire: what is sent, and what comes back."""

import json

import httpx2
import pytest

from domain import errors
from domain.patterns import Rejection
from infrastructure.claude_pattern_writer import ClaudePatternWriter, UnconfiguredPatternWriter

ANSWER = {
    "understood": True,
    "reason": "",
    "pattern": r"\b[\w.%+-]+@[\w.-]+\.[A-Za-z]{2,}\b",
    "explanation": "Matches e-mail addresses such as john.doe@example.com.",
    "replacement": "REDACTED",
    "columns": ["Email"],
    "should_match": ["john.doe@example.com"],
    "should_not_match": ["john.doe at example"],
}


def writer_answering(handler):
    """A writer whose HTTP requests go to `handler` instead of the network."""
    writer = ClaudePatternWriter("sk-ant-test-key", "claude-test-model", timeout=5)
    transport = httpx2.MockTransport(handler)
    writer._client = writer._client.with_options(
        http_client=httpx2.Client(transport=transport), max_retries=0
    )
    return writer


def message(answer: dict, stop_reason="end_turn") -> httpx2.Response:
    return httpx2.Response(
        200,
        json={
            "id": "msg_1",
            "type": "message",
            "role": "assistant",
            "model": "claude-test-model",
            "content": [{"type": "text", "text": json.dumps(answer)}],
            "stop_reason": stop_reason,
            "stop_sequence": None,
            "usage": {"input_tokens": 900, "output_tokens": 200},
        },
    )


def test_the_answer_becomes_a_suggestion_with_its_backslashes_intact():
    suggestion = writer_answering(lambda request: message(ANSWER)).write("find email addresses")

    assert suggestion.pattern == r"\b[\w.%+-]+@[\w.-]+\.[A-Za-z]{2,}\b"
    assert (suggestion.replacement, suggestion.columns) == ("REDACTED", ["Email"])
    assert suggestion.should_match == ["john.doe@example.com"]


def test_only_the_request_leaves_the_process():
    sent = []

    def handler(request):
        sent.append(json.loads(request.content))
        return message(ANSWER)

    writer_answering(handler).write("Find email addresses in the Email column.")

    (body,) = sent
    # The adapter is given a sentence and nothing else, so there is no file data it could send.
    # This pins the request's shape, so that adding any would have to be done on purpose here.
    assert body["messages"] == [
        {"role": "user", "content": "Find email addresses in the Email column."}
    ]
    assert set(body) == {
        "model",
        "max_tokens",
        "system",
        "messages",
        "output_config",
        "thinking",
    }
    assert body["output_config"]["format"]["type"] == "json_schema"
    assert body["thinking"] == {"type": "disabled"}


def test_a_refused_pattern_is_sent_back_with_the_reason():
    sent = []

    def handler(request):
        sent.append(json.loads(request.content))
        return message(ANSWER)

    rejected = Rejection(r"(\S+)+@", "It did not finish on the input 'aaaa!'.")
    writer_answering(handler).write("find email addresses", rejected)

    content = sent[0]["messages"][0]["content"]
    assert content.startswith("find email addresses")
    assert r"(\\S+)+@" in content or r"(\S+)+@" in content
    assert "It did not finish on the input 'aaaa!'." in content


def test_a_request_that_describes_nothing_to_find_is_not_understood():
    answer = ANSWER | {"understood": False, "reason": "It asks about the weather.", "pattern": ""}
    with pytest.raises(errors.PatternNotUnderstood, match="It asks about the weather."):
        writer_answering(lambda request: message(answer)).write("what is the weather today")


@pytest.mark.parametrize(
    ("status", "error_type", "expected"),
    [
        (429, "rate_limit_error", errors.LLMUnavailable),
        (500, "api_error", errors.LLMUnavailable),
        (529, "overloaded_error", errors.LLMUnavailable),
        (401, "authentication_error", errors.LLMRejectedRequest),
        (400, "invalid_request_error", errors.LLMRejectedRequest),
    ],
)
def test_api_failures_become_domain_errors(status, error_type, expected):
    def handler(request):
        body = {"type": "error", "error": {"type": error_type, "message": "no"}}
        return httpx2.Response(status, json=body)

    with pytest.raises(expected):
        writer_answering(handler).write("find email addresses")


def test_a_network_failure_is_transient():
    def handler(request):
        raise httpx2.ConnectError("no route to host")

    with pytest.raises(errors.LLMUnavailable):
        writer_answering(handler).write("find email addresses")


def test_the_api_key_is_not_in_any_error_a_user_could_see():
    def handler(request):
        assert request.headers["x-api-key"] == "sk-ant-test-key"  # it does go to the API
        body = {"type": "error", "error": {"type": "authentication_error", "message": "bad key"}}
        return httpx2.Response(401, json=body)

    with pytest.raises(errors.LLMRejectedRequest) as refusal:
        writer_answering(handler).write("find email addresses")
    assert "sk-ant" not in refusal.value.message


def test_without_a_key_nothing_can_be_written():
    writer = UnconfiguredPatternWriter()
    assert writer.is_configured is False
    with pytest.raises(errors.LLMNotConfigured):
        writer.write("find email addresses")
