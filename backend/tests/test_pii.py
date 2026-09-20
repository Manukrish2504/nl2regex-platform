"""Finding personal data: what a language model is shown, and what is done with its answer."""

import re

import pytest
from fakes import FakeAdviceCache, FakeClassifier, FakePatternCache, FakeProbe, FakeWriter

from domain import errors
from domain.advice import Finding
from domain.operations import MaskCells, Replace
from infrastructure.pattern_probe import SubprocessPatternProbe
from services.patterns import PatternService
from services.pii import PATTERNS, PiiService, profile, shape_of

COLUMNS = ["id", "name", "email", "notes"]
ROWS = [
    ["1", "John Doe", "john.doe@example.com", "Call +1 (632) 132-1488 after five."],
    ["2", "Jane Smith", "JANE_S99@domain.co.uk", "Alt contact: jsmith7@mail.org"],
    ["3", "Zoë Müller", None, "No issues reported."],
]


def service(classifier, probe=None):
    patterns = PatternService(FakeWriter(), FakePatternCache(), probe or FakeProbe())
    return PiiService(classifier, FakeAdviceCache(), patterns)


# --- what leaves -------------------------------------------------------------------------------


def test_a_shape_keeps_punctuation_and_length_and_no_letter_or_digit():
    assert shape_of("John.Doe99@example.com") == "Aaaa.Aaa99@aaaaaaa.aaa"
    assert shape_of("+1 (632) 132-1488") == "+9 (999) 999-9999"
    assert shape_of("Zoë Müller") == "Aaa Aaaaaa"  # a letter is a letter in any alphabet


def test_nothing_of_the_original_values_is_in_a_profile():
    sent = profile(COLUMNS, ROWS, [])
    shown = " ".join(shape for item in sent for shape in item.shapes + item.token_shapes)

    assert not re.search(r"[b-zB-Z0-8]", shown)  # only the stand-ins a, A and 9
    assert [item.column for item in sent] == COLUMNS  # column names are sent as they are


def test_an_address_buried_in_free_text_shows_in_the_token_shapes():
    notes = profile(COLUMNS, ROWS, ["notes"])[0]
    assert "aaaaaa9@aaaa.aaa" in notes.token_shapes
    assert not any("@" in shape for shape in notes.shapes) or len(notes.shapes) > 1


def test_variants_of_one_kind_share_a_place_so_other_kinds_are_not_crowded_out():
    rows = [[f"{'a' * n}@x.com"] for n in range(3, 40)] + [["555-123-4567"]]
    shapes = profile(["contact"], rows, [])[0].shapes
    assert len(shapes) == 2  # one for every e-mail address, however long, and one for the phone


def test_only_the_wanted_columns_are_profiled():
    assert [item.column for item in profile(COLUMNS, ROWS, ["email"])] == ["email"]


# --- what is done with the answer ------------------------------------------------------------


def test_findings_become_operations_with_our_own_patterns():
    classifier = FakeClassifier(
        [
            Finding("email", "email", "its shapes are e-mail addresses"),
            Finding("notes", "email", "e-mail addresses inside the text"),
            Finding("notes", "phone", "phone numbers inside the text"),
            Finding("name", "name", "people's names"),
        ]
    )
    operations, report = service(classifier).plan(COLUMNS, ROWS, [])

    assert operations == [
        Replace(PATTERNS["email"][1], "[EMAIL]", ["email", "notes"]),
        Replace(PATTERNS["phone"][1], "[PHONE]", ["notes"]),
        MaskCells("[NAME]", ["name"]),  # whole cells last: masking leaves nothing to match
    ]
    assert [row["kind"] for row in report["operations"]] == ["email", "phone", "name"]
    assert len(report["findings"]) == 4


def test_a_finding_about_a_column_that_was_not_sent_is_dropped():
    classifier = FakeClassifier(
        [Finding("salary", "identifier", "invented"), Finding("email", "email", "e-mails")]
    )
    operations, report = service(classifier).plan(COLUMNS, ROWS, [])

    assert [operation.columns for operation in operations] == [["email"]]
    assert report["skipped"][0]["column"] == "salary"


def test_a_pattern_the_model_wrote_goes_through_the_same_checks():
    good = Finding("notes", "other", "employee IDs", r"EMP-\d{5}", ["EMP-12345"], ["EMP-12"])
    bad = Finding("notes", "other", "badge IDs", r"(\w+)+$", ["x"], [])
    operations, report = service(
        FakeClassifier([good, bad]), probe=FakeProbe(unsafe=[bad.pattern])
    ).plan(COLUMNS, ROWS, [])

    assert operations == [Replace(r"EMP-\d{5}", "[REDACTED]", ["notes"])]
    assert "not safe to run" in report["skipped"][0]["skipped_because"]


def test_nothing_found_is_said_plainly_and_nothing_is_rewritten():
    with pytest.raises(errors.NothingToChange, match="No personal data was found"):
        service(FakeClassifier([])).plan(COLUMNS, ROWS, [])


def test_the_same_profile_is_not_sent_twice():
    classifier = FakeClassifier([Finding("email", "email", "e-mails")])
    pii = service(classifier)
    _, first = pii.plan(COLUMNS, ROWS, [])
    _, second = pii.plan(COLUMNS, ROWS, [])

    assert (first["from_cache"], second["from_cache"]) == (False, True)
    assert len(classifier.calls) == 1


# --- our own patterns ---------------------------------------------------------------------------

EXAMPLES = {
    "email": (
        ["john.doe@example.com", "mail JANE_S99@domain.co.uk now"],
        ["john at example.com", "@handle", "example.com"],
    ),
    "phone": (
        ["+1 (632) 132-1488", "484-928-1106", "+44 20 7161 2258", "4849281106", "(555) 123-4567"],
        ["2020-09-20", "03/12/2024", "12345", "$1,234.56", "order 123-45"],
    ),
    "ssn": (["123-45-6789", "SSN: 987-65-4321"], ["12-345-6789", "555-123-4567", "1123-45-67890"]),
    "card": (
        ["4111 1111 1111 1111", "4111-1111-1111-1111", "4111111111111111"],
        ["1234", "555-123-4567", "2024-03-12"],
    ),
    "ip": (["192.168.1.1", "from 10.0.0.255 port"], ["1.2.3", "version 1.2", "1.2.3.4.5"]),
    "url": (["https://example.com/path?q=1", "see http://x.io now"], ["example.com", "ftp"]),
}


@pytest.mark.parametrize("kind", PATTERNS)
def test_each_pattern_matches_what_it_should_and_nothing_else(kind):
    pattern = re.compile(PATTERNS[kind][1])
    should_match, should_not_match = EXAMPLES[kind]
    assert [text for text in should_match if not pattern.search(text)] == []
    assert [text for text in should_not_match if pattern.search(text)] == []


@pytest.mark.parametrize("kind", PATTERNS)
def test_each_pattern_passes_the_real_safety_probe(kind):
    SubprocessPatternProbe().check(PATTERNS[kind][1])


def test_a_phone_pattern_replaces_the_number_and_nothing_around_it():
    pattern = re.compile(PATTERNS["phone"][1])
    assert pattern.sub("[PHONE]", "Alt contact: +1 (552) 718-5333.") == "Alt contact: [PHONE]."
