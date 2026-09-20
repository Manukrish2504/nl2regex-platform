"""Asks Claude about a file: which columns hold personal data, and how to make one column's
spellings consistent. What each is shown is as little as the question allows."""

import json
from dataclasses import asdict

import pydantic

from domain.advice import ColumnProfile, Finding
from domain.errors import LLMUnavailable
from infrastructure import claude_api

# Part of the cache key. Raise it whenever the instructions below change what Claude would answer.
INSTRUCTIONS_VERSION = 1

PII_INSTRUCTIONS = """You are shown the columns of a data file: each column's name, how much of it is blank, and SHAPES taken from a sample of its values. A shape is a value with every letter replaced by a (A for a capital) and every digit by 9. Punctuation, spaces and length are unchanged, so "aaaa.aaa@aaaaaaa.aaa" is an e-mail address and "+9 (999) 999-9999" is a phone number. You never see a real value.

shapes are those of whole values, most common first. token_shapes are those of the words inside the values that are not plain words, most common first. In a free-text column every value has its own shape, so what is buried in it shows only in token_shapes: "aaaa99@aaaa.aa" there means that some values contain an e-mail address.

Say which columns contain personal data, and of what kind. Give one finding per column and kind. A free-text column can have several, for example notes that contain e-mail addresses and phone numbers.

Kinds that are found inside a cell, wherever they occur:
  email, phone, ssn (US social security number), card (payment card number), ip (IPv4 address), url
Kinds that make the whole cell sensitive:
  name (a person's name), address (a postal address), date_of_birth, identifier (a national ID, passport, licence or account number that identifies a person)
Use "other" only for personal data that fits none of these and has a regular format. Then give a regular expression for it that works the same in Python and Java, runs in linear time and matches the whole thing and nothing around it, with 3 strings it should match and 3 it should not. For every other kind leave pattern null and the example lists empty.

Judge a column by its name and its shapes together. A column called "name" whose shapes are "Aaaa Aaa" holds people's names; a column called "product_name" probably does not. Do not flag row numbers and counters, dates that are not birth dates (a signup or order date), countries, cities, amounts, statuses, or free text in which no personal data is visible.

reason: one short sentence that a person can check, such as "its shapes are e-mail addresses"."""  # noqa: E501

STANDARDISE_INSTRUCTIONS = """You are given the name of one column of a data file and its distinct values. Many of them are different spellings of the same thing ("USA", "U.S.", "us", "United States"). Map values to one canonical form each, so that the column becomes consistent.

- Choose the canonical form the way the instruction says. With no instruction, prefer the clearest full form, in the capitalisation a careful person would write ("United States", not "us").
- Merge only values that certainly mean the same thing. When unsure, leave a value as it is.
- Return a pair for every value that should change. from_value must be copied from the list exactly, character for character. Return nothing for a value that stays as it is.
- Do not invent values, do not fill in missing data, and do not translate anything except to unify spellings of the same thing."""  # noqa: E501


class _FindingAnswer(pydantic.BaseModel):
    column: str
    kind: str
    reason: str
    pattern: str | None
    should_match: list[str]
    should_not_match: list[str]


class _PiiAnswer(pydantic.BaseModel):
    findings: list[_FindingAnswer]


class _Pair(pydantic.BaseModel):
    from_value: str
    to_value: str


class _StandardiseAnswer(pydantic.BaseModel):
    pairs: list[_Pair]


class ClaudePiiClassifier:
    def __init__(self, api_key: str, model: str, timeout: float):
        self._client = claude_api.client(api_key, timeout)
        self._model = model

    def classify(self, profiles: list[ColumnProfile]) -> list[Finding]:
        # Shapes and column names. A ColumnProfile cannot hold a value, so none can be sent.
        content = json.dumps([asdict(profile) for profile in profiles], ensure_ascii=False)
        answer = claude_api.ask(
            self._client, self._model, "find-personal-data", PII_INSTRUCTIONS, content, _PiiAnswer
        )
        if answer is None:
            raise LLMUnavailable("The language model did not finish its answer. Try again.")
        return [Finding(**finding.model_dump()) for finding in answer.findings]


class ClaudeValueStandardiser:
    def __init__(self, api_key: str, model: str, timeout: float):
        self._client = claude_api.client(api_key, timeout)
        self._model = model

    def standardise(
        self, column: str, values: list[str], instruction: str | None
    ) -> list[tuple[str, str]]:
        content = json.dumps(
            {"column": column, "instruction": instruction or "", "values": values},
            ensure_ascii=False,
        )
        answer = claude_api.ask(
            self._client,
            self._model,
            "standardise-values",
            STANDARDISE_INSTRUCTIONS,
            content,
            _StandardiseAnswer,
            max_tokens=8192,  # up to 300 pairs
        )
        if answer is None:
            raise LLMUnavailable("The language model did not finish its answer. Try again.")
        return [(pair.from_value, pair.to_value) for pair in answer.pairs]
