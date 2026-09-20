"""Making one column's spellings consistent: what is sent, and what is done with the answer."""

import pytest
from fakes import FakeAdviceCache, FakeStandardiser

from domain import errors
from domain.operations import MapValues
from services.standardise import MAX_LENGTH, MAX_VALUES, StandardiseService

COUNTS = [("USA", 40), ("us", 30), (None, 20), ("Germany", 15), ("Deutschland", 5)]
PAIRS = [("USA", "United States"), ("us", "United States"), ("Deutschland", "Germany")]


def service(pairs=PAIRS):
    standardiser = FakeStandardiser(pairs)
    return StandardiseService(standardiser, FakeAdviceCache()), standardiser


def test_the_columns_distinct_values_are_sent_and_the_blank_is_not():
    standardise, model = service()
    standardise.plan("country", COUNTS, "use full English names")

    assert model.calls == [
        ("country", ["USA", "us", "Germany", "Deutschland"], "use full English names")
    ]


def test_the_answer_becomes_a_mapping_and_a_report_with_row_counts():
    operations, report = service()[0].plan("country", COUNTS, None)

    assert operations == [
        MapValues(
            "country", {"USA": "United States", "us": "United States", "Deutschland": "Germany"}
        )
    ]
    assert (report["distinct_before"], report["distinct_after"]) == (4, 2)
    assert {"from": "us", "to": "United States", "rows": 30} in report["mapping"]


def test_invented_keys_and_entries_that_change_nothing_are_dropped():
    pairs = [
        ("Atlantis", "Nowhere"),
        ("Germany", "Germany"),
        ("us", "  "),
        ("USA", "United States"),
    ]
    operations, _ = service(pairs)[0].plan("country", COUNTS, None)
    assert operations == [MapValues("country", {"USA": "United States"})]


@pytest.mark.parametrize(
    ("counts", "reason"),
    [
        ([(f"value {n}", 1) for n in range(MAX_VALUES + 1)], "more than 300 different values"),
        ([("x" * (MAX_LENGTH + 1), 3), ("y", 2)], "longer than 60 characters"),
    ],
)
def test_a_column_that_is_not_a_set_of_categories_is_refused_before_anything_is_sent(
    counts, reason
):
    standardise, model = service()
    with pytest.raises(errors.NotCategorical, match=reason):
        standardise.plan("email", counts, None)
    assert model.calls == []  # names or e-mail addresses never reach the language model


def test_values_that_are_already_consistent_are_left_alone():
    with pytest.raises(errors.NothingToChange, match="already look consistent"):
        service(pairs=[])[0].plan("country", COUNTS, None)
    with pytest.raises(errors.NothingToChange, match="fewer than two"):
        service()[0].plan("country", [("USA", 9), (None, 1)], None)


def test_the_same_question_is_not_asked_twice():
    standardise, model = service()
    _, first = standardise.plan("country", COUNTS, None)
    _, second = standardise.plan("country", list(reversed(COUNTS)), None)  # order does not matter

    assert (first["from_cache"], second["from_cache"]) == (False, True)
    assert len(model.calls) == 1
