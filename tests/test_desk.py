"""The knowledge desk: an agent's deferred lookups into its own knowledge base (D-112)."""

from __future__ import annotations

from typing import Any

from lexarena.agents.desk import NO_LOOKUPS, OMITTED, KnowledgeDesk
from lexarena.agents.knowledge import CaseLibrary
from lexarena.config import load_config
from lexarena.schemas.agent import KnowledgeLookup
from lexarena.schemas.retrieval import PrecedentCard, PrecedentExcerpt, SearchResult
from tests.conftest import CONFIG_V1
from tests.test_layer1 import statute_view
from tests.test_reflection import lesson

CFG = load_config(CONFIG_V1)
STATUTE = "<statute A>"


def card(uid: str) -> PrecedentCard:
    return PrecedentCard(
        precedent_uid=uid,
        precedent_id=f"<id {uid}>",
        case_title="<title>",
        forum="NCLAT",
        decision_date="2020-01-01",
        final_order="<order>",
        statutes=[],
        rule="<rule>",
        matched="<passage>",
        score=1.0,
        score_kind="VECTOR",
    )


def library(searches: list[str]) -> CaseLibrary:
    def search(query: str, statutes: Any = None) -> SearchResult:
        searches.append(query)
        return (
            SearchResult(hits=[card("U1")], statute_filter=[], ignored_statutes=[])
            if "hit" in query
            else SearchResult(hits=[], statute_filter=[], ignored_statutes=[])
        )

    def get_precedent(uid: str, part: str = "ratio") -> PrecedentExcerpt | None:
        if uid != "U1":
            return None
        return PrecedentExcerpt(
            precedent_uid="U1", precedent_id="<id>", case_title="<t>", decision_date="2020", part="ratio", text="<r>"
        )

    return CaseLibrary({"find_authority": search, "find_similar_cases": search, "get_precedent": get_precedent})


def desk(searches: list[str] | None = None, cfg: Any = CFG) -> KnowledgeDesk:
    view = statute_view(STATUTE)
    return KnowledgeDesk(
        statute=lambda q: view if q == STATUTE else None,
        library=library(searches if searches is not None else []),
        lessons=lambda q, k: [lesson(1), lesson(2)][:k],
        cfg=cfg,
    )


def ask(kind: str, query: str) -> KnowledgeLookup:
    return KnowledgeLookup.model_validate({"kind": kind, "query": query})


def test_each_part_of_the_knowledge_base_answers() -> None:
    answer = desk().serve([ask("STATUTE", STATUTE), ask("AUTHORITY_SEARCH", "a hit"), ask("LESSONS", "<advice>")])
    assert set(answer.statutes) == {STATUTE} and [c.precedent_uid for c in answer.cards] == ["U1"]
    assert "<lesson 1>" in answer.text and "[U1]" in answer.text


def test_unknown_statutes_and_precedents_are_reported_not_guessed() -> None:
    answer = desk().serve([ask("STATUTE", "<no such section>"), ask("PRECEDENT", "U9")])
    assert answer.statutes == {} and "no provision" in answer.text and "no precedent" in answer.text


def test_the_same_count_and_budget_cap_for_every_side() -> None:
    searches: list[str] = []
    n = CFG.session.lookups_per_turn
    answer = desk(searches).serve([ask("SIMILAR_CASES", f"q{i}") for i in range(n + 2)])
    assert len(searches) == n and "beyond the limit" in answer.text
    tiny = CFG.model_copy(update={"session": CFG.session.model_copy(update={"lookup_tokens": 5})})
    assert OMITTED in desk(cfg=tiny).serve([ask("STATUTE", STATUTE)]).text


def test_no_lookups_says_how_to_ask() -> None:
    assert desk().serve([]).text == NO_LOOKUPS
