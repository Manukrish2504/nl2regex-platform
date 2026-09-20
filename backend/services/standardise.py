"""Use-case: make one column's spellings consistent ("USA", "U.S." and "us" become one value).

Spark counts the column's distinct values, the language model maps each to a canonical form, and
Spark applies the mapping to every row. The model sees the distinct values of that one column and
is never called per row.
"""

import hashlib
import json

from domain.errors import NotCategorical, NothingToChange
from domain.operations import MapValues, Operation
from domain.ports import AdviceCache, ValueStandardiser

# Beyond these a column is not a set of categories: it is names, e-mails or free text, and that
# is not sent to a third party. The limits are a privacy guard first and a cost guard second.
MAX_VALUES = 300
MAX_LENGTH = 60


class StandardiseService:
    def __init__(self, standardiser: ValueStandardiser, cache: AdviceCache):
        self._standardiser = standardiser
        self._cache = cache

    def plan(
        self, column: str, counts: list[tuple[str | None, int]], instruction: str | None
    ) -> tuple[list[Operation], dict]:
        """`counts` is the column's distinct values with their row counts, most frequent first,
        from one more than MAX_VALUES asked of the engine, so that "too many" can be told."""
        filled = [(value, rows) for value, rows in counts if value]
        if len(filled) > MAX_VALUES:
            raise NotCategorical(f"it has more than {MAX_VALUES} different values.")
        longest = max((len(value) for value, _ in filled), default=0)
        if longest > MAX_LENGTH:
            raise NotCategorical(f"some of its values are longer than {MAX_LENGTH} characters.")
        if len(filled) < 2:
            raise NothingToChange("That column has fewer than two different values.")

        values = [value for value, _ in filled]
        pairs, from_cache = self._pairs(column, values, instruction)
        # The answer is not trusted: a key the model invented would silently do nothing, so it
        # is dropped here, as is an entry that maps a value to itself.
        sent = set(values)
        mapping = {
            before: after.strip()
            for before, after in pairs
            if before in sent and after.strip() and after.strip() != before
        }
        if not mapping:
            raise NothingToChange("Those values already look consistent, so nothing was changed.")

        rows_by_value = dict(filled)
        after_values = {mapping.get(value, value) for value in values}
        report = {
            "column": column,
            "mapping": [
                {"from": before, "to": after, "rows": rows_by_value[before]}
                for before, after in sorted(mapping.items(), key=lambda item: (item[1], item[0]))
            ],
            "distinct_before": len(values),
            "distinct_after": len(after_values),
            "from_cache": from_cache,
        }
        return [MapValues(column, mapping)], report

    def _pairs(
        self, column: str, values: list[str], instruction: str | None
    ) -> tuple[list[tuple[str, str]], bool]:
        sent = {"column": column, "values": sorted(values), "instruction": instruction or ""}
        key = "standardise:" + hashlib.sha256(json.dumps(sent, sort_keys=True).encode()).hexdigest()
        cached = self._cache.get(key)
        if cached is not None:
            return [tuple(pair) for pair in cached["pairs"]], True
        pairs = self._standardiser.standardise(column, values, instruction)
        self._cache.put(key, {"pairs": [list(pair) for pair in pairs]})
        return pairs, False
