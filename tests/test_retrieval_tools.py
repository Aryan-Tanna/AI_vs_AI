"""Retrieval tools (BUILD_PLAN Step 5), offline: a fake reader stands in for the scoped Qdrant reader, whose
cut-off and exclusion enforcement is tested against the real Qdrant in test_retrieval_scope.py.

Placeholder data only (non-negotiable 1, D-033).
"""

from __future__ import annotations

import inspect
from typing import Any

import pytest

from lexarena.retrieval.tools import RetrievalTools, tools_for
from lexarena.schemas.case import AgentCaseView
from lexarena.schemas.retrieval import AGENT_PRECEDENT_FIELDS, CaseScope
from lexarena.schemas.statute_alias import StatuteAliasTable
from lexarena.storage.cases import PROMPT_HIDDEN_METADATA
from lexarena.storage.policy import Role
from tests import builders

INSTRUCTION = "<query instruction> "
KNOWN = {"TEST_ACT_SEC_7", "TEST_ACT_SEC_9"}
NO_ALIASES = StatuteAliasTable(aliases=[])


def stored_payload(uid: str, **change: Any) -> dict[str, Any]:
    base: dict[str, Any] = {k: f"<{k}>" for k in AGENT_PRECEDENT_FIELDS}
    base.update(
        precedent_uid=uid,
        precedent_id=f"<id {uid}>",
        statutes_cited=["TEST_ACT_SEC_7"],
        statutes_normalized=["TEST_ACT_SEC_7"],
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
        return [(p, 0.5) for p in self.payloads[:limit]]

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


def agent_view() -> AgentCaseView:
    view = builders.case_doc("CASE-T")["agent_view"]
    for name in PROMPT_HIDDEN_METADATA:
        view["metadata"].pop(name, None)
    return AgentCaseView.model_validate({**view, "case_id": "CASE-T"})


def make(payloads: list[dict[str, Any]] | None = None, top_k: int = 3) -> tuple[RetrievalTools, FakeReader, Any]:
    reader = FakeReader(payloads if payloads is not None else [stored_payload(f"U{i}") for i in range(5)])
    embedder = RecordingEmbedder()
    tools = RetrievalTools(
        reader=reader,
        case=agent_view(),
        embedder=embedder,
        known_statutes=KNOWN,
        aliases=NO_ALIASES,
        top_k=top_k,
        query_instruction=INSTRUCTION,
    )
    return tools, reader, embedder


def test_facts_search_is_symmetric_and_queries_the_facts_multivector() -> None:
    tools, reader, embedder = make()
    result = tools.find_similar_cases("<facts>")
    assert embedder.texts == ["<facts>"]
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


def test_hits_show_the_allow_listed_fields_only() -> None:
    tools, _, _ = make()
    hit = tools.find_authority("<proposition>").hits[0]
    dumped = hit.model_dump()
    assert set(dumped) == {*AGENT_PRECEDENT_FIELDS, "score"}
    assert "is_overruled" not in dumped and "content_hash" not in dumped and hit.score == 0.5


def test_get_precedent_by_uid() -> None:
    tools, _, _ = make()
    found = tools.get_precedent("U2")
    assert found is not None and found.precedent_uid == "U2" and found.score is None
    assert tools.get_precedent("<missing or out of scope>") is None


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
