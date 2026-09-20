"""Writing a pattern from a request: the cache, the checks, the repair loop and the safety probe."""

import time

import pytest
from fakes import FakePatternCache, FakeProbe, FakeWriter

from domain import errors
from domain.patterns import PatternSuggestion
from infrastructure.pattern_probe import DEADLINE_SECONDS, SubprocessPatternProbe, pump_strings
from services.patterns import PatternService, normalise


def suggestion(pattern, should_match=("a@x.com",), should_not_match=("nothing",)):
    return PatternSuggestion(
        pattern,
        "explained",
        should_match=list(should_match),
        should_not_match=list(should_not_match),
    )


GOOD = suggestion(r"\S+@\S+")


def service(writer, probe=None, cache=None):
    return PatternService(writer, cache or FakePatternCache(), probe or FakeProbe())


# --- the cache -----------------------------------------------------------------------------


def test_the_same_request_is_sent_to_the_language_model_once():
    writer = FakeWriter(GOOD)
    patterns = service(writer)

    first, first_cached = patterns.suggest("Find email addresses.")
    second, second_cached = patterns.suggest("Find email addresses.")

    assert (first_cached, second_cached) == (False, True)
    assert first == second == GOOD
    assert len(writer.calls) == 1


@pytest.mark.parametrize(
    "variant", ["find email addresses", "  FIND   Email\taddresses  ", "Find email addresses!"]
)
def test_requests_that_differ_only_in_case_spacing_or_a_full_stop_share_an_entry(variant):
    assert normalise(variant) == normalise("Find email addresses.")


def test_a_different_request_is_a_different_entry():
    writer = FakeWriter(GOOD, suggestion(r"\d+", ["12"], ["ab"]))
    patterns = service(writer)
    patterns.suggest("find email addresses")
    patterns.suggest("find numbers")
    assert len(writer.calls) == 2


# --- the checks, and asking again ----------------------------------------------------------


@pytest.mark.parametrize(
    ("bad", "reason"),
    [
        (suggestion(r"[a-z"), "unterminated character set"),
        (suggestion(""), "The pattern is empty."),
        (suggestion(r"(?P<user>\S+)@\S+"), "Java's regex engine does not accept"),
        (suggestion(r"\d+", should_match=["a@x.com"]), "it finds nothing in 'a@x.com'"),
        # What matched is quoted: usually a valid match inside a longer string.
        (suggestion(r"\d+", ["12"], ["a1b"]), "it matches '1' in 'a1b'"),
    ],
)
def test_a_pattern_that_fails_a_check_is_sent_back_with_the_reason(bad, reason):
    writer = FakeWriter(bad, GOOD)
    result, _ = service(writer).suggest("find email addresses")

    assert result == GOOD
    (_, first_rejection), (_, second_rejection) = writer.calls
    assert first_rejection is None
    assert second_rejection.pattern == bad.pattern
    assert reason in second_rejection.reason


def test_a_pattern_the_probe_refuses_is_sent_back_too():
    unsafe = suggestion(r"(\S+)+@\S+")
    writer = FakeWriter(unsafe, GOOD)
    result, _ = service(writer, probe=FakeProbe(unsafe=[unsafe.pattern])).suggest("find emails")

    assert result == GOOD
    assert "not safe to run" in writer.calls[1][1].reason


def test_only_a_pattern_that_passed_is_cached():
    cache = FakePatternCache()
    service(FakeWriter(suggestion(r"[a-z"), GOOD), cache=cache).suggest("find email addresses")
    assert list(cache.entries.values()) == [GOOD]


def test_after_three_refusals_the_request_fails_with_the_last_reason():
    bad = suggestion(r"\d+", should_match=["a@x.com"])
    writer, cache = FakeWriter(bad, bad, bad), FakePatternCache()
    with pytest.raises(errors.PatternNotVerified, match="it finds nothing in 'a@x.com'"):
        service(writer, cache=cache).suggest("find email addresses")

    assert len(writer.calls) == 3
    assert cache.entries == {}


def test_a_request_that_is_not_understood_is_not_asked_again():
    writer = FakeWriter(errors.PatternNotUnderstood("It asks about the weather."))
    with pytest.raises(errors.PatternNotUnderstood):
        service(writer).suggest("what is the weather today")
    assert len(writer.calls) == 1


# --- the probe: a real child process, against real patterns --------------------------------

CATASTROPHIC = [
    r"(a+)+$",
    r"(a|aa)+$",
    r"(.*a){12}$",
    r"(\w+\s?)*$",
    r"(\d+)*$",
    # The e-mail validator from OWASP's page on regex denial of service.
    r"^([a-zA-Z0-9])(([\-.]|[_]+)?([a-zA-Z0-9]+))*(@){1}[a-z0-9]+[.]{1}(([a-z]{2,3})|([a-z]{2,3}[.]{1}[a-z]{2,3}))$",
]
ORDINARY = [
    r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b",
    r"[\w.+-]+@[\w-]+\.[\w.]+",
    r"\+?\d[\d\s().-]{7,}\d",
    r"https?://\S+",
    r"\b\d{4}-\d{2}-\d{2}\b",
    r"\s+$",  # quadratic on a long run of spaces, and harmless on real cells: it must pass
    r"(?i)n/a",
    r"\b(?:\d{1,3}\.){3}\d{1,3}\b",
]


@pytest.mark.parametrize("pattern", CATASTROPHIC)
def test_a_pattern_that_backtracks_catastrophically_is_refused_within_the_deadline(pattern):
    started = time.monotonic()
    with pytest.raises(errors.UnsafePattern, match="on the input"):
        SubprocessPatternProbe().check(pattern)
    assert time.monotonic() - started < DEADLINE_SECONDS + 1.5  # the child was killed, not awaited


@pytest.mark.parametrize("pattern", ORDINARY)
def test_an_ordinary_pattern_passes(pattern):
    SubprocessPatternProbe().check(pattern)


def test_the_refusal_names_the_input_that_hung_it():
    with pytest.raises(errors.UnsafePattern) as refusal:
        SubprocessPatternProbe().check(r"(x+x+)+y")
    assert "'xxxxxxxx" in refusal.value.message  # built from the pattern's own characters


def test_pump_strings_use_the_patterns_own_characters():
    strings = pump_strings(r"(x+x+)+y")
    assert any(text.startswith("xxxx") for text in strings)
    assert all(text.endswith("!") for text in strings)
    assert {len(text) for text in strings} > {33}  # short runs, and long ones
