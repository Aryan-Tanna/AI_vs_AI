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


def test_a_statute_one_side_looked_up_stays_out_of_the_shared_sections() -> None:
    """D-112 with SPEC E6: after one side looks up a provision the case did not have, both sides' shared inputs are
    still identical; the provision is in that side's side-specific part only, and in its own law for THEMIS."""
    from typing import cast

    from lexarena.agents.knowledge import ExperienceBase, LawyerKnowledge, RegulationMemory
    from lexarena.agents.lawyer import FOUND_HEADING, Lawyer
    from lexarena.llm.client import LLMClient
    from lexarena.prompts import PromptStore
    from lexarena.schemas.agent import LawyerDraft
    from lexarena.schemas.base import Side
    from lexarena.storage.temporal import StatuteView
    from lexarena.themis_local.verify import LawContext
    from tests.conftest import PROMPTS_ROOT
    from tests.judge_fixtures import agent_view

    other = "<statute B>"
    case = agent_view()
    found = statute_view(other)

    def resolve(q: str) -> StatuteView | None:
        return found if q == other else None

    lawyers: dict[Side, Lawyer] = {}
    sides: list[Side] = ["PETITIONER", "RESPONDENT"]
    for side in sides:
        law = LawContext(views={STATUTE: statute_view(STATUTE)}, alternatives=None, predicates={})
        lawyers[side] = Lawyer(
            side,
            case,
            LawyerKnowledge(RegulationMemory(law), library([]), ExperienceBase([])),
            cast(LLMClient, None),
            PromptStore(PROMPTS_ROOT),
            CFG,
            session_id="S",
            desk=KnowledgeDesk(
                statute=resolve,
                library=library([]),
                lessons=lambda q, k: [],
                cfg=CFG,
            ),
        )
    asks = LawyerDraft(text="<t>", issues_addressed=[], claims=[], lookups=[ask("STATUTE", other)])
    lawyers["PETITIONER"].answer_lookups(asks)
    p = lawyers["PETITIONER"].assemble_turn(3, "REBUTTAL", [], None)
    r = lawyers["RESPONDENT"].assemble_turn(3, "REBUTTAL", [], None)
    assert p.shared == r.shared
    assert FOUND_HEADING in p.side_specific["lookups"] and FOUND_HEADING not in r.side_specific["lookups"]
    assert other in lawyers["PETITIONER"].knowledge.regulation.law.views
    assert other not in lawyers["RESPONDENT"].knowledge.regulation.law.views


def test_what_the_side_already_holds_is_answered_as_nothing_new() -> None:
    """D-135: LEX-D re-asked for a statute it held (DEV_0008 turn 8); the desk says so instead of serving it again."""
    answer = desk().serve(
        [ask("STATUTE", STATUTE), ask("AUTHORITY_SEARCH", "a hit")],
        held_statutes={STATUTE},
        held_precedents={"U1"},
    )
    assert answer.statutes == {} and answer.cards == []
    assert "already in your regulation memory" in answer.text and "nothing new" in answer.text


def test_holding_rules_are_the_same_for_both_sides() -> None:
    """The desk has no notion of side: the same lookups and holdings give the same answer (non-negotiable 3)."""
    a = desk().serve([ask("AUTHORITY_SEARCH", "a hit")], held_statutes=set(), held_precedents=set())
    b = desk().serve([ask("AUTHORITY_SEARCH", "a hit")], held_statutes=set(), held_precedents=set())
    assert a.text == b.text and [c.precedent_uid for c in a.cards] == ["U1"]


def test_held_authorities_survive_brackets_and_bare_ids_but_never_invented_ones() -> None:
    """D-152: DEV_0013 (both sides) and DEV_0015 (one side) started the hearing with none of their research because
    the model wrote the IDs in brackets. Brackets, spacing and a bare ID of a card research returned are accepted; an
    ID research never returned, or a bare ID two returned cards share, is still dropped."""
    from lexarena.agents.lawyer import held_cards

    a, b = card("A#1"), card("B#2")
    a = a.model_copy(update={"precedent_id": "A"})
    b = b.model_copy(update={"precedent_id": "B"})
    twin = card("B#3").model_copy(update={"precedent_id": "B"})
    got = held_cards(["[A#1]", " A ", "<invented>", "B"], [a, b, twin])
    assert [c.precedent_uid for c in got] == ["A#1"]  # A once; B is ambiguous; the invented one never held
    assert [c.precedent_uid for c in held_cards(["B#2"], [a, b, twin])] == ["B#2"]


def test_the_closed_case_library_finds_and_fetches_nothing() -> None:
    """D-153: the NO_CASE_LIBRARY ablation; research still runs, it simply returns nothing, for both sides alike."""
    from lexarena.agents.knowledge import CaseLibrary
    from lexarena.schemas.agent import ResearchQuery

    closed = CaseLibrary.closed()
    assert closed.can_search
    assert closed.research([ResearchQuery(kind="authority", query="<q>", statutes=[])], 3) == []
    assert closed.fetch("<uid>") is None


def test_a_card_shows_what_its_precedent_was_decided_under_and_its_facts() -> None:
    """D-153: DEV_0015's majority used a Companies Act ratio for an IBC question; the card now says so."""
    from lexarena.agents.knowledge import render_cards

    c = card("U9").model_copy(update={"cited": ["COMPANIES_ACT_2013_SEC_73(4)"], "facts": "<facts>"})
    text = render_cards([c])
    assert "decided under: COMPANIES_ACT_2013_SEC_73(4)" in text and "facts: <facts>" in text
    assert "decided under" not in render_cards([card("U1")])  # nothing invented when a record lists none


def test_the_facts_line_skips_party_identities() -> None:
    from lexarena.retrieval.tools import PARTY_SECTION

    facts = "1. PARTY IDENTITIES: <names>. 2. COMMERCIAL TRANSACTION: <transaction>."
    assert PARTY_SECTION.sub("", facts, count=1).strip() == "2. COMMERCIAL TRANSACTION: <transaction>."
    assert PARTY_SECTION.sub("", "<no numbered sections>", count=1) == "<no numbered sections>"
