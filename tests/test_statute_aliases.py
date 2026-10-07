"""Statute citation aliases (Q-028, D-049; idea ported from Parth Shah's `ingest/statute_alias.py`).

The precedent DB and the Law DB spell the same act differently. A reviewed alias table in data maps a citation
prefix to the Law DB's prefix; the general resolution rules then run on the rewritten citation. Placeholder IDs
only: the code must not depend on any real record (D-033).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from lexarena.ingest.precedents import prepare_precedents, read_precedent_sources
from lexarena.schemas.statute_alias import StatuteAliasTable
from lexarena.statute_ids import load_statute_aliases, missing_alias_targets, normalize_statutes, resolve_statute_id
from tests.fakes import WordEmbedder
from tests.test_precedent_prep import KNOWN, precedent, write_jsonl

KNOWN_ALIASED = KNOWN | {"TA2001_SEC241", "TEST_RULES2001_R11", "TEST_ACT_SEC_13_2"}
ALIASES = StatuteAliasTable.model_validate(
    {
        "aliases": [
            {"cited_prefix": "TEST_ACT_2001_LONG_SEC_", "law_db_prefix": "TA2001_SEC", "reason": "<same act>"},
            {"cited_prefix": "TEST_RULES_2001_RULE_", "law_db_prefix": "TEST_RULES2001_R", "reason": "<same rules>"},
        ]
    }
)


def test_alias_rewrites_the_act_prefix() -> None:
    assert resolve_statute_id("TEST_ACT_2001_LONG_SEC_241", KNOWN_ALIASED, ALIASES) == ("TA2001_SEC241", "alias")
    assert resolve_statute_id("TEST_RULES_2001_RULE_11", KNOWN_ALIASED, ALIASES) == ("TEST_RULES2001_R11", "alias")


def test_alias_then_sub_section_resolves_to_the_section() -> None:
    assert resolve_statute_id("TEST_ACT_2001_LONG_SEC_241_3", KNOWN_ALIASED, ALIASES)[0] == "TA2001_SEC241"
    assert resolve_statute_id("TEST_ACT_2001_LONG_SEC_241(3)", KNOWN_ALIASED, ALIASES)[0] == "TA2001_SEC241"


def test_alias_never_lands_on_a_different_section() -> None:
    for cited in ("TEST_ACT_2001_LONG_SEC_24", "TEST_ACT_2001_LONG_SEC_2410", "TEST_ACT_2001_LONG_SEC_41"):
        assert resolve_statute_id(cited, KNOWN_ALIASED, ALIASES) == (None, "unresolved"), cited


def test_free_text_spelling_is_normalised_before_aliasing() -> None:
    assert resolve_statute_id("Test Act 2001 Long, Sec 241", KNOWN_ALIASED, ALIASES) == ("TA2001_SEC241", "alias")


def test_bracketed_sub_section_prefers_an_exact_sub_section_id() -> None:
    assert resolve_statute_id("TEST_ACT_SEC_13(2)", KNOWN_ALIASED) == ("TEST_ACT_SEC_13_2", "bracket_as_underscore")


def test_without_aliases_nothing_changes() -> None:
    assert resolve_statute_id("TEST_ACT_2001_LONG_SEC_241", KNOWN_ALIASED) == (None, "unresolved")
    found, unresolved = normalize_statutes(["TEST_ACT_SEC_7", "TEST_ACT_2001_LONG_SEC_241"], KNOWN_ALIASED)
    assert found == ["TEST_ACT_SEC_7"] and unresolved == ["TEST_ACT_2001_LONG_SEC_241"]


def test_longest_cited_prefix_wins() -> None:
    table = StatuteAliasTable.model_validate(
        {
            "aliases": [
                {"cited_prefix": "TEST_ACT_", "law_db_prefix": "NOWHERE_", "reason": "<broad>"},
                {"cited_prefix": "TEST_ACT_2001_LONG_SEC_", "law_db_prefix": "TA2001_SEC", "reason": "<narrow>"},
            ]
        }
    )
    assert resolve_statute_id("TEST_ACT_2001_LONG_SEC_241", KNOWN_ALIASED, table)[0] == "TA2001_SEC241"


@pytest.mark.parametrize(
    "bad",
    [
        {"cited_prefix": "lower_", "law_db_prefix": "X_", "reason": "r"},
        {"cited_prefix": "A_", "law_db_prefix": "X_", "reason": ""},
        {"cited_prefix": "A_", "law_db_prefix": "A_", "reason": "maps to itself"},
    ],
)
def test_malformed_alias_is_rejected(bad: dict[str, str]) -> None:
    with pytest.raises(ValidationError):
        StatuteAliasTable.model_validate({"aliases": [bad]})


def test_duplicate_cited_prefix_is_rejected() -> None:
    entry = {"cited_prefix": "A_", "law_db_prefix": "X_", "reason": "r"}
    with pytest.raises(ValidationError):
        StatuteAliasTable.model_validate({"aliases": [entry, {**entry, "law_db_prefix": "Y_"}]})


def test_targets_that_match_no_law_db_id_are_reported(tmp_path: Path) -> None:
    path = tmp_path / "aliases.json"
    path.write_text(json.dumps(ALIASES.model_dump(mode="json")), encoding="utf-8")
    table = load_statute_aliases(path)
    assert missing_alias_targets(table, KNOWN_ALIASED) == []
    assert missing_alias_targets(table, KNOWN) == ["TA2001_SEC", "TEST_RULES2001_R"]


def test_derived_fields_have_their_own_hash(tmp_path: Path) -> None:
    """A Law DB or alias change alters statutes_normalized without touching the record, so ingestion must see
    it through derived_hash; content_hash (which decides re-embedding) stays the same."""
    write_jsonl(tmp_path, "a.jsonl", [precedent("P1", statutes_cited=["TEST_ACT_2001_LONG_SEC_241"])])
    before = prepare_precedents(*read_precedent_sources(tmp_path), KNOWN_ALIASED, WordEmbedder(), window_tokens=50)
    after = prepare_precedents(
        *read_precedent_sources(tmp_path), KNOWN_ALIASED, WordEmbedder(), window_tokens=50, aliases=ALIASES
    )
    [b], [a] = before.points, after.points
    assert b.payload["statutes_normalized"] == [] and a.payload["statutes_normalized"] == ["TA2001_SEC241"]
    assert b.content_hash == a.content_hash
    assert b.payload["derived_hash"] != a.payload["derived_hash"]
    assert after.report.statute_resolution == {"alias": 1}
