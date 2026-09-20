"""One way of asking Claude for a structured answer, shared by every adapter that does."""

import logging
import time

import anthropic
import pydantic

from domain.errors import LLMRejectedRequest, LLMUnavailable

logger = logging.getLogger(__name__)


def client(api_key: str, timeout: float) -> anthropic.Anthropic:
    return anthropic.Anthropic(api_key=api_key, timeout=timeout, max_retries=2)


def ask[Answer: pydantic.BaseModel](
    api: anthropic.Anthropic,
    model: str,
    task: str,
    instructions: str,
    content: str,
    answer_type: type[Answer],
    max_tokens: int = 2048,
) -> Answer | None:
    """The parsed answer, or None if Claude stopped without a complete one.

    Structured outputs constrain decoding to the answer type's schema, so a regex arrives with
    its backslashes intact, which asking for "JSON with a regex in it" does not guarantee.
    """
    started = time.monotonic()
    try:
        message = api.messages.parse(
            model=model,
            max_tokens=max_tokens,
            system=instructions,
            messages=[{"role": "user", "content": content}],
            output_format=answer_type,
            # These tasks need no deliberation, and thinking triples the wait.
            thinking={"type": "disabled"},
        )
    except anthropic.APIStatusError as error:
        if error.status_code == 429 or error.status_code >= 500:
            raise LLMUnavailable() from error
        # A bad key, no credit, an unknown model: nothing the user can fix, so it is logged
        # for the operator. The status and type only: never the request, never the key.
        logger.error("Claude refused a request: %s %s", error.status_code, type(error).__name__)
        raise LLMRejectedRequest() from error
    except anthropic.APIConnectionError as error:  # includes timeouts
        raise LLMUnavailable() from error

    # What was asked and what it cost. Never the content: it may hold a user's words or values.
    logger.info(
        "Claude answered: task=%s model=%s seconds=%.1f tokens_in=%s tokens_out=%s",
        task,
        model,
        time.monotonic() - started,
        message.usage.input_tokens,
        message.usage.output_tokens,
    )
    return message.parsed_output
