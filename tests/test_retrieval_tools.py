"""Retrieval tools (BUILD_PLAN Step 5, D-052; compact cards and reranking, D-055), offline: a fake reader stands
in for the scoped Qdrant reader (whose cut-off and exclusions are tested in test_retrieval_scope.py) and a fake
reranker scores passages by marker.

Placeholder data only (non-negotiable 1, D-033).
"""

from __future__ import annotations

import inspect
from typing import Any

import pytest

from lexarena.retrieval.tools import RetrievalTools, tools_for
from lexarena.schemas.case import AgentCaseView
from lexarena.schemas.retrieval import AGENT_PRECEDENT_FIELDS, CaseScope, PrecedentExcerpt, PrecedentView
from lexarena.schemas.statute_alias import StatuteAliasTable
from lexarena.storage.cases import PROMPT_HIDDEN_METADATA
from lexarena.storage.policy import Role
from tests import builders

INSTRUCTION = "<query instruction> "
KNOWN = {"TEST_ACT_SEC_7", "TEST_ACT_SEC_9"}
NO_ALIASES = StatuteAliasTable(aliases=[])
CARD_TOKENS = 6


def stored_payload(uid: str, **change: Any) -> dict[str, Any]:
    base: dict[str, Any] = {k: f"<{k}>" for k in AGENT_PRECEDENT_FIELDS}
    base.update(
        precedent_uid=uid,
        precedent_id=f"<id {uid}>",
        statutes_cited=["TEST_ACT_SEC_7"],
        statutes_normalized=["TEST_ACT_SEC_7"],
        material_facts=f"1. PARTY IDENTITIES: <names {uid}> 2. COMMERCIAL TRANSACTION: <deal {uid}> "
        f"3. DEFAULT METRICS: <default {uid}>",
        ratio_decidendi=f"1. ABSTRACT LEGAL RULE: <rule {uid}> 2. STATUTORY INTERPRETATION: <reading {uid}> "
        f"3. EVIDENTIARY TEST APPLIED: <test {uid}> 4. DEFINITIVE CONCLUSION: <outcome {uid}>",
        is_overruled=True,
        content_hash="<hash>",
        derived_hash="<hash>",
        source_file="<file>",
        decision_date_ts="<ts>",
    )
    return {**base, **change}


class FakeReader:
    def __init__(self, payloads: list[dict[str, Any]]) -> None:
        self.payloads = payloads
        self.calls: list[tuple[str, Any, list[str], int]] = []

    def search(self, using: str, query: Any, statutes: list[str], limit: int) -> list[tuple[dict[str, Any], float]]:
        self.calls.append((using, query, statutes, limit))
        return [(p, 0.9 - i / 100) for i, p in enumerate(self.payloads[:limit])]

    def get(self, precedent_uid: str) -> dict[str, Any] | None:
        return next((p for p in self.payloads if p["precedent_uid"] == precedent_uid), None)


class RecordingEmbedder:
    dim = 2

    def __init__(self) -> None:
        self.texts: list[str] = []

    def count_tokens(self, text: str) -> int:
        return len(text.split())

    def embed(self, texts: list[str]) -> list[list[float]]:
        self.texts += texts
        return [[float(len(t)), 1.0] for t in texts]


class MarkerReranker:
    """Scores a passage by the first marker it contains; records every (query, passage) pair."""

    def __init__(self, scores: dict[str, float]) -> None:
        self.scores = scores
        self.pairs: list[tuple[str, str]] = []

    def score(self, query: str, passages: list[str]) -> list[float]:
        self.pairs += [(query, p) for p in passages]
        return [next((v for k, v in self.scores.items() if k in p), 0.0) for p in passages]


def agent_view() -> AgentCaseView:
    view = builders.case_doc("CASE-T")["agent_view"]
    for name in PROMPT_HIDDEN_METADATA:
        view["metadata"].pop(name, None)
    return AgentCaseView.model_validate({**view, "case_id": "CASE-T"})


def make(
    payloads: list[dict[str, Any]] | None = None,
    reranker: MarkerReranker | None = None,
    top_k: int = 3,
    pool: int = 5,
) -> tuple[RetrievalTools, FakeReader, RecordingEmbedder]:
    reader = FakeReader(payloads if payloads is not None else [stored_payload(f"U{i}") for i in range(8)])
    embedder = RecordingEmbedder()
    tools = RetrievalTools(
        reader=reader,
        case=agent_view(),
        embedder=embedder,
        reranker=reranker,
        known_statutes=KNOWN,
        aliases=NO_ALIASES,
        top_k=top_k,
        candidate_pool=pool,
        card_text_tokens=CARD_TOKENS,
        query_instruction=INSTRUCTION,
    )
    return tools, reader, embedder


# ---------------------------------------------------------------- vector search


def test_facts_search_is_symmetric_and_queries_the_facts_multivector() -> None:
    tools, reader, embedder = make()
    result = tools.find_similar_cases("<facts>")
    assert embedder.texts[0] == "<facts>"  # the query, as is; then the hits' sections, to show which matched
    assert all("PARTY IDENTITIES" not in t for t in embedder.texts)
    using, query, statutes, limit = reader.calls[0]
    assert using == "facts" and len(query) == 1 and isinstance(query[0], list)  # one vector inside a multivector query
    assert statutes == [] and limit == 3 and len(result.hits) == 3


def test_authority_search_prefixes_the_query_instruction_to_the_query_only() -> None:
    tools, reader, embedder = make()
    tools.find_authority("<proposition>")
    assert embedder.texts == [INSTRUCTION + "<proposition>"]
    assert reader.calls[0][0] == "ratio" and isinstance(reader.calls[0][1][0], float)


def test_statutes_are_optional_and_resolved_to_law_db_ids() -> None:
    tools, reader, _ = make()
    result = tools.find_similar_cases("<facts>", statutes=["TEST_ACT_SEC_7(1)", "Test Act, Sec 9", "<unknown act>"])
    assert reader.calls[0][2] == ["TEST_ACT_SEC_7", "TEST_ACT_SEC_9"]
    assert result.statute_filter == ["TEST_ACT_SEC_7", "TEST_ACT_SEC_9"]
    assert result.ignored_statutes == ["<unknown act>"]


def test_only_unresolvable_statutes_returns_nothing_rather_than_an_unfiltered_search() -> None:
    tools, reader, _ = make()
    result = tools.find_authority("<proposition>", statutes=["<unknown act>"])
    assert result.hits == [] and result.ignored_statutes == ["<unknown act>"] and reader.calls == []


# ---------------------------------------------------------------- compact cards (D-055)


def test_hits_are_compact_cards_without_the_full_record() -> None:
    tools, _, _ = make()
    card = tools.find_authority("<proposition>").hits[0]
    dumped = card.model_dump()
    assert "material_facts" not in dumped and "ratio_decidendi" not in dumped and "summary" not in dumped
    assert "is_overruled" not in dumped and "content_hash" not in dumped
    assert card.rule == "ABSTRACT LEGAL RULE: <rule U0>"
    assert card.statutes == ["TEST_ACT_SEC_7"] and card.score_kind == "VECTOR"


def test_card_text_is_capped_at_the_configured_tokens() -> None:
    long_rule = "1. ABSTRACT LEGAL RULE: " + " ".join(f"w{i}" for i in range(50))
    tools, _, _ = make([stored_payload("U0", ratio_decidendi=long_rule)])
    card = tools.find_authority("<proposition>").hits[0]
    assert len(card.rule.split()) <= CARD_TOKENS + 1  # the cap, plus the cut marker
    assert card.rule.endswith("…")


# ---------------------------------------------------------------- reranking (D-055)


def test_reranker_fetches_the_candidate_pool_and_reorders_it() -> None:
    reranker = MarkerReranker({"<reading U4>": 5.0, "<rule U2>": 3.0, "<test U1>": 1.0})
    tools, reader, _ = make(reranker=reranker)
    result = tools.find_authority("<proposition>")
    assert reader.calls[0][3] == 5  # candidate_pool, not top_k
    assert [c.precedent_uid for c in result.hits] == ["U4", "U2", "U1"]
    assert [c.score for c in result.hits] == [5.0, 3.0, 1.0] and result.hits[0].score_kind == "RERANKER"


def test_reranker_sees_the_raw_query_and_each_ratio_part_separately() -> None:
    reranker = MarkerReranker({})
    tools, _, _ = make(reranker=reranker)
    tools.find_authority("<proposition>")
    assert {q for q, _ in reranker.pairs} == {"<proposition>"}  # no embedding instruction for the cross-encoder
    passages = [p for _, p in reranker.pairs if "U0" in p]
    assert passages == [
        "ABSTRACT LEGAL RULE: <rule U0>",
        "STATUTORY INTERPRETATION: <reading U0>",
        "EVIDENTIARY TEST APPLIED: <test U0>",
    ]  # part 4, the case-specific conclusion, is never a passage


def test_facts_reranking_uses_facts_sections_without_party_identities() -> None:
    reranker = MarkerReranker({"<default U3>": 2.0})
    tools, _, _ = make(reranker=reranker)
    result = tools.find_similar_cases("<facts>")
    assert all("PARTY IDENTITIES" not in p for _, p in reranker.pairs)
    assert result.hits[0].precedent_uid == "U3"
    assert result.hits[0].matched == "DEFAULT METRICS: <default U3>"


def test_matched_is_the_best_scoring_passage() -> None:
    reranker = MarkerReranker({"<test U0>": 4.0, "<rule U0>": 1.0})
    tools, _, _ = make([stored_payload("U0")], reranker=reranker)
    assert tools.find_authority("<proposition>").hits[0].matched == "EVIDENTIARY TEST APPLIED: <test U0>"


def test_without_a_reranker_top_k_comes_straight_from_the_vector_search() -> None:
    tools, reader, _ = make()
    result = tools.find_similar_cases("<facts>")
    assert reader.calls[0][3] == 3
    assert [c.precedent_uid for c in result.hits] == ["U0", "U1", "U2"]


class MarkerEmbedder(RecordingEmbedder):
    """[1, 0] for text with the marker, [0, 1] otherwise: cosine picks the marked passage."""

    def embed(self, texts: list[str]) -> list[list[float]]:
        self.texts += texts
        return [[1.0, 0.0] if "<default" in t else [0.0, 1.0] for t in texts]


def test_without_a_reranker_facts_cards_show_the_section_closest_to_the_query() -> None:
    tools, _, _ = make()
    tools._embedder = MarkerEmbedder()
    card = tools.find_similar_cases("<default query>").hits[0]
    assert card.matched == "DEFAULT METRICS: <default U0>"


def test_without_a_reranker_authority_cards_do_not_repeat_the_rule() -> None:
    tools, _, _ = make()
    card = tools.find_authority("<proposition>").hits[0]
    assert card.rule == "ABSTRACT LEGAL RULE: <rule U0>" and card.matched == ""


# ---------------------------------------------------------------- fetch by ID


def test_get_precedent_returns_one_part_by_default() -> None:
    tools, _, _ = make()
    found = tools.get_precedent("U2")
    assert isinstance(found, PrecedentExcerpt) and found.part == "ratio"
    assert found.text.startswith("1. ABSTRACT LEGAL RULE: <rule U2>")


@pytest.mark.parametrize(
    ("part", "field"),
    [("facts", "material_facts"), ("issues", "legal_issues"), ("summary", "summary"), ("ratio", "ratio_decidendi")],
)
def test_get_precedent_parts(part: str, field: str) -> None:
    tools, reader, _ = make()
    found = tools.get_precedent("U1", part=part)  # type: ignore[arg-type]
    assert isinstance(found, PrecedentExcerpt) and found.text == reader.payloads[1][field]


def test_get_precedent_order_part_holds_both_order_fields() -> None:
    tools, reader, _ = make()
    found = tools.get_precedent("U1", part="order")
    assert isinstance(found, PrecedentExcerpt)
    assert reader.payloads[1]["final_order"] in found.text and reader.payloads[1]["operative_order"] in found.text


def test_get_precedent_all_returns_the_allow_listed_view() -> None:
    tools, _, _ = make()
    found = tools.get_precedent("U2", part="all")
    assert isinstance(found, PrecedentView) and set(found.model_dump()) == {*AGENT_PRECEDENT_FIELDS, "score"}


def test_get_precedent_out_of_scope_is_none() -> None:
    tools, _, _ = make()
    assert tools.get_precedent("<missing or out of scope>") is None


def test_unknown_part_is_rejected() -> None:
    tools, _, _ = make()
    with pytest.raises(ValueError, match="part"):
        tools.get_precedent("U1", part="everything")  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("item_id", "kind"),
    [("F1", "STIPULATED_FACT"), ("C1", "CONTESTED_FACT"), ("EX-1", "EXHIBIT"), ("AM1", "AMOUNT")],
)
def test_get_record_item(item_id: str, kind: str) -> None:
    tools, _, _ = make()
    result = tools.get_record_item(item_id)
    assert result is not None and result.kind == kind


def test_unknown_record_item_is_none() -> None:
    tools, _, _ = make()
    assert tools.get_record_item("F999") is None


# ---------------------------------------------------------------- roles and scope


def test_lawyers_search_and_verifiers_and_judges_only_fetch() -> None:
    tools, _, _ = make()
    search = {"find_similar_cases", "find_authority"}
    fetch = {"get_precedent", "get_record_item"}
    assert set(tools_for(Role.LAWYER, tools)) == search | fetch
    for role in (Role.THEMIS_LOCAL, Role.THEMIS_GLOBAL, Role.JUDGE):
        assert set(tools_for(role, tools)) == fetch, role
    with pytest.raises(PermissionError):
        tools_for(Role.EVALUATOR, tools)


def test_no_tool_takes_a_date_or_an_exclusion_list() -> None:
    """The scope is bound at construction; an agent has no argument with which to widen it."""
    tools, _, _ = make()
    scope_words = {"date", "before", "cutoff", "cut_off", "exclude", "excluded", "scope", "as_of"}
    for name, fn in tools_for(Role.LAWYER, tools).items():
        params = set(inspect.signature(fn).parameters)
        assert not {p for p in params if any(w in p for w in scope_words)}, name


def test_case_scope_comes_from_the_full_case() -> None:
    case = builders.case("CASE-S", build_marker="<excluded id>", date_marker="2001-02-03")
    scope = CaseScope.from_case(case)
    assert scope.decided_before.isoformat() == "2001-02-03"
    assert scope.excluded_precedent_ids == ["<excluded id>"]
