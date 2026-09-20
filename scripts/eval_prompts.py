"""Measure how well each Claude model turns varied phrasings into a correct regex.

    cd backend && uv run python ../scripts/eval_prompts.py [--env ../.env] [model ...]

Every request goes through the real pipeline (the instructions, the four checks, the repair loop),
with the cache switched off. A request passes when its pattern finds every string it should,
finds nothing in the strings it should not, and replaces exactly the expected span.

This calls the paid API: about 45 requests per model. The key is read from the environment, or
from the file given with --env, and is never printed.
"""

import argparse
import json
import logging
import os
import re
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from domain.errors import DomainError  # noqa: E402
from infrastructure.claude_pattern_writer import ClaudePatternWriter  # noqa: E402
from infrastructure.pattern_probe import SubprocessPatternProbe  # noqa: E402
from services.patterns import PatternService  # noqa: E402

MODELS = ["claude-haiku-4-5-20251001", "claude-sonnet-5", "claude-opus-5"]
# US dollars per million tokens (input, output). Assumed list prices, for a rough cost column only:
# check them against current pricing before quoting the result.
PRICES = {"claude-haiku-4-5-20251001": (1, 5), "claude-sonnet-5": (3, 15), "claude-opus-5": (5, 25)}

# One entry per intent: several ways of asking, and what any correct pattern must do.
# "replace" maps an input to its expected output when every match becomes <X>; it checks that the
# match covers the thing described and nothing around it.
CORPUS = [
    {
        "intent": "email addresses",
        "ask": [
            "find email addresses",
            "e-mails",
            "anything that looks like an email address",
            "Find email addresses in the Email column and replace them with 'REDACTED'.",
        ],
        "match": ["john.doe@example.com", "JANE_SMITH@Domain.co.uk", "a+b@x.io"],
        "no_match": ["john at example.com", "@handle", "example.com"],
        "replace": {"mail john@x.com, then call": "mail <X>, then call"},
    },
    {
        "intent": "US phone numbers",
        "ask": ["US phone numbers", "american telephone numbers", "phone numbers"],
        "match": ["555-123-4567", "(555) 123-4567", "+1 555 123 4567"],
        "no_match": ["2024-03-12", "12345", "1.50"],
        "replace": {"call 555-123-4567 today": "call <X> today"},
    },
    {
        "intent": "a phone number in one given format",
        "ask": ["phone numbers like (555) 123-4567"],
        "match": ["(555) 123-4567", "call (212) 555-0199 now"],
        "no_match": ["2024-03-12", "12345", "1.50"],
        "replace": {"call (555) 123-4567 today": "call <X> today"},
    },
    {
        "intent": "URLs",
        "ask": ["URLs", "web links", "http and https links"],
        "match": ["https://example.com/path?q=1", "http://x.io"],
        "no_match": ["example", "see the docs", "a.b"],
        "replace": {"see https://x.io/a now": "see <X> now"},
    },
    {
        "intent": "ISO dates",
        "ask": [
            "dates written like 2024-03-12",
            "ISO dates (year-month-day)",
            "dates in YYYY-MM-DD format",
        ],
        "match": ["2024-03-12", "1999-12-31"],
        "no_match": ["12/03/2024", "2024-3-1", "20240312"],
        "replace": {"joined 2024-03-12.": "joined <X>."},
    },
    {
        "intent": "US dates with slashes",
        "ask": ["dates like 03/12/2024", "dates in MM/DD/YYYY format"],
        "match": ["03/12/2024", "12/31/1999"],
        "no_match": ["2024-03-12", "3.12.2024", "03/2024"],
        "replace": {"due 03/12/2024 at noon": "due <X> at noon"},
    },
    {
        "intent": "IPv4 addresses",
        "ask": ["IP addresses", "IPv4 addresses", "ip addresses such as 192.168.1.1"],
        "match": ["192.168.1.1", "10.0.0.255"],
        "no_match": ["1.2.3", "version 1.2", "abc.def.ghi.jkl"],
        "replace": {"from 10.0.0.1 port 80": "from <X> port 80"},
    },
    {
        "intent": "payment card numbers",
        "ask": [
            "credit card numbers",
            "16-digit card numbers, with or without spaces or dashes",
            "payment card numbers",
        ],
        "match": ["4111 1111 1111 1111", "4111-1111-1111-1111", "4111111111111111"],
        "no_match": ["1234", "555-123-4567", "2024-03-12"],
        "replace": {"card 4111 1111 1111 1111 exp": "card <X> exp"},
    },
    {
        "intent": "leading and trailing whitespace",
        "ask": [
            "leading and trailing whitespace",
            "spaces at the start or end of the cell",
            "trim the cell",
        ],
        "match": ["  padded", "padded  "],
        "no_match": ["not padded", "x"],
        "replace": {"  two words  ": "<X>two words<X>"},
    },
    {
        "intent": "hashtags",
        "ask": ["hashtags", "hashtags like #sale", "social media hashtags"],
        "match": ["#sale", "big #BlackFriday2024 deals"],
        "no_match": ["# heading", "sale", "number 5"],
        "replace": {"big #sale now": "big <X> now"},
    },
    {
        "intent": "US social security numbers",
        "ask": ["US social security numbers", "SSNs like 123-45-6789", "social security numbers"],
        "match": ["123-45-6789", "SSN: 987-65-4321"],
        "no_match": ["12-345-6789", "555-123-4567", "2024-03-12"],
        "replace": {"ssn 123-45-6789 on file": "ssn <X> on file"},
    },
    {
        "intent": "words in capitals",
        "ask": ["words written entirely in capital letters", "words in ALL CAPS"],
        "match": ["URGENT", "reply ASAP please"],
        "no_match": ["Hello there", "hello"],
        "replace": {"this is URGENT now": "this is <X> now"},
    },
    {
        "intent": "words in capitals, two letters or more",
        "ask": ["ALL CAPS words of two or more letters"],
        "match": ["URGENT", "reply ASAP please"],
        "no_match": ["Hello there", "hello", "A"],
        "replace": {"this is URGENT now": "this is <X> now"},
    },
    {
        "intent": "dollar amounts",
        "ask": [
            "dollar amounts like $1,234.56",
            "prices in US dollars",
            "amounts of money in dollars",
        ],
        "match": ["$1,234.56", "$99", "costs $5.00"],
        "no_match": ["1234", "USD", "50%"],
        "replace": {"paid $1,234.56 today": "paid <X> today"},
    },
    {
        "intent": "repeated spaces",
        "ask": ["two or more spaces in a row", "runs of multiple spaces"],
        "match": ["a  b", "a     b"],
        "no_match": ["a b", "ab"],
        "replace": {"a  b   c": "a<X>b<X>c"},
    },
    {
        "intent": "N/A placeholders",
        "ask": ["N/A placeholders, in any capitalisation", "the text n/a, upper or lower case"],
        "match": ["N/A", "n/a"],
        "no_match": ["NASA", "banana"],
        "replace": {"N/A": "<X>"},
    },
    {
        "intent": "cells that are only N/A",
        "ask": ["cells whose whole value is N/A, in any capitalisation"],
        "match": ["N/A", "n/a"],
        "no_match": ["NASA", "banana", "N/A for now"],
        "replace": {"N/A": "<X>"},
    },
]


class NoCache:
    def get(self, request):
        return None

    def put(self, request, suggestion):
        pass


class Usage(logging.Handler):
    """The adapter logs the tokens of every call. This reads them back, per thread."""

    def __init__(self):
        super().__init__()
        self.calls = []

    def emit(self, record):
        if "Claude wrote a pattern" in record.getMessage():
            _, seconds, tokens_in, tokens_out, _ = record.args
            self.calls.append((record.thread, seconds, tokens_in, tokens_out))


def judge(pattern: str, case: dict) -> str | None:
    compiled = re.compile(pattern)
    for text in case["match"]:
        if not compiled.search(text):
            return f"found nothing in {text!r}"
    for text in case["no_match"]:
        if compiled.search(text):
            return f"matched {text!r}"
    for text, expected in case["replace"].items():
        got = compiled.sub(lambda _m: "<X>", text)
        if got != expected:
            return f"{text!r} became {got!r}, not {expected!r}"
    return None


def evaluate(model: str, api_key: str) -> dict:
    usage = Usage()
    logger = logging.getLogger("infrastructure.claude_pattern_writer")
    logger.addHandler(usage)
    logger.setLevel(logging.INFO)
    service = PatternService(
        ClaudePatternWriter(api_key, model, timeout=60), NoCache(), SubprocessPatternProbe()
    )

    def one(item):
        case, request = item
        started = time.monotonic()
        try:
            suggestion, _ = service.suggest(request)
            problem = judge(suggestion.pattern, case)
            pattern = suggestion.pattern
        except DomainError as error:
            problem, pattern = f"{error.code}: {error.message}", ""
        return {
            "intent": case["intent"],
            "request": request,
            "pattern": pattern,
            "problem": problem,
            "seconds": time.monotonic() - started,
        }

    items = [(case, request) for case in CORPUS for request in case["ask"]]
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(one, items))
    logger.removeHandler(usage)

    price_in, price_out = PRICES.get(model, (0, 0))
    tokens_in = sum(call[2] for call in usage.calls)
    tokens_out = sum(call[3] for call in usage.calls)
    seconds = sorted(result["seconds"] for result in results)
    return {
        "model": model,
        "requests": len(results),
        "passed": sum(result["problem"] is None for result in results),
        "api_calls": len(usage.calls),
        "median_seconds": round(statistics.median(seconds), 1),
        "p90_seconds": round(seconds[int(len(seconds) * 0.9)], 1),
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "cost_usd": round((tokens_in * price_in + tokens_out * price_out) / 1e6, 3),
        "failures": [result for result in results if result["problem"]],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("models", nargs="*", default=MODELS)
    parser.add_argument("--env", help="a .env file holding ANTHROPIC_API_KEY or CLAUDE_API_KEY")
    parser.add_argument("--json", help="also write the results to this file")
    args = parser.parse_args()

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if args.env:
        for line in Path(args.env).read_text().splitlines():
            name, _, value = line.partition("=")
            if name.strip() in ("ANTHROPIC_API_KEY", "CLAUDE_API_KEY"):
                api_key = value.strip().strip("\"'")
    if not api_key:
        raise SystemExit("No API key: set ANTHROPIC_API_KEY or pass --env.")

    reports = [evaluate(model, api_key) for model in args.models]
    print("| Model | Passed | API calls | Median | 90th pct | Tokens in / out | Cost |")
    print("|---|---|---|---|---|---|---|")
    for report in reports:
        print(
            f"| `{report['model']}` | {report['passed']} / {report['requests']} "
            f"| {report['api_calls']} | {report['median_seconds']} s | {report['p90_seconds']} s "
            f"| {report['tokens_in']:,} / {report['tokens_out']:,} | ${report['cost_usd']} |"
        )
    for report in reports:
        for failure in report["failures"]:
            print(f"\n{report['model']} failed {failure['request']!r} ({failure['intent']})")
            print(f"    pattern {failure['pattern']!r}\n    because {failure['problem']}")
    if args.json:
        Path(args.json).write_text(json.dumps(reports, indent=2))


if __name__ == "__main__":
    main()
