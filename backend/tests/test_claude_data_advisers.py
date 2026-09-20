"""The two questions asked about a file, with the network replaced at the wire: what is sent."""

import json

import httpx2

from domain.advice import ColumnProfile
from infrastructure.claude_data_advisers import ClaudePiiClassifier, ClaudeValueStandardiser
from services.pii import profile

ROWS = [
    ["1", "John Doe", "john.doe@example.com", "Call +1 (632) 132-1488 after five."],
    ["2", "Jane Smith", "jane_s99@domain.co.uk", "Alt contact: jsmith7@mail.org"],
]
COLUMNS = ["id", "name", "email", "notes"]


def answering(adapter, answer: dict, sent: list):
    """Point an adapter's HTTP at a handler that records the request and returns `answer`."""

    def handler(request):
        sent.append(json.loads(request.content))
        body = {
            "id": "msg_1",
            "type": "message",
            "role": "assistant",
            "model": "claude-test-model",
            "content": [{"type": "text", "text": json.dumps(answer)}],
            "stop_reason": "end_turn",
            "stop_sequence": None,
            "usage": {"input_tokens": 500, "output_tokens": 100},
        }
        return httpx2.Response(200, json=body)

    adapter._client = adapter._client.with_options(
        http_client=httpx2.Client(transport=httpx2.MockTransport(handler)), max_retries=0
    )
    return adapter


def test_the_personal_data_question_carries_shapes_and_column_names_and_no_value():
    sent = []
    finding = {
        "column": "email",
        "kind": "email",
        "reason": "its shapes are e-mail addresses",
        "pattern": None,
        "should_match": [],
        "should_not_match": [],
    }
    classifier = answering(
        ClaudePiiClassifier("sk-ant-test", "claude-test-model", 5), {"findings": [finding]}, sent
    )
    findings = classifier.classify(profile(COLUMNS, ROWS, []))

    (body,) = sent
    (message,) = body["messages"]
    # Every value that was sampled, and every word of it: none may appear in what was sent.
    words = {word.strip(".,:()") for row in ROWS for cell in row for word in cell.split()}
    leaked = [word for word in words if len(word) > 2 and word in message["content"]]
    assert leaked == []
    assert json.loads(message["content"])[2] == {
        "column": "email",
        "blank_share": 0.0,
        "shapes": ["aaaa.aaa@aaaaaaa.aaa", "aaaa_a99@aaaaaa.aa.aa"],
        "token_shapes": ["aaaa.aaa@aaaaaaa.aaa", "aaaa_a99@aaaaaa.aa.aa"],
    }
    assert (findings[0].column, findings[0].kind) == ("email", "email")


def test_a_profile_cannot_hold_a_value_so_none_can_be_sent():
    # The adapter's only input. Its fields are a name, a number and shapes.
    assert set(ColumnProfile.__dataclass_fields__) == {
        "column",
        "blank_share",
        "shapes",
        "token_shapes",
    }


def test_the_standardise_question_carries_that_columns_values_and_nothing_else():
    sent = []
    answer = {"pairs": [{"from_value": "us", "to_value": "United States"}]}
    standardiser = answering(
        ClaudeValueStandardiser("sk-ant-test", "claude-test-model", 5), answer, sent
    )
    pairs = standardiser.standardise("country", ["USA", "us"], "use full English names")

    (body,) = sent
    assert json.loads(body["messages"][0]["content"]) == {
        "column": "country",
        "instruction": "use full English names",
        "values": ["USA", "us"],
    }
    assert set(body) == {"model", "max_tokens", "system", "messages", "output_config", "thinking"}
    assert pairs == [("us", "United States")]
