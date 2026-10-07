"""The scoped precedent reader against the real Qdrant (BUILD_PLAN Step 5, SPEC B1, B2, B7; D-052).

The cut-off and exclusion list are applied inside Qdrant by a reader bound to one case's scope; session roles
have no unscoped read. Placeholder records only.

Run with: pytest --run-integration -m integration
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from pathlib import Path

import pytest
from qdrant_client import QdrantClient

from lexarena.retrieval.tools import RetrievalTools
from lexarena.schemas.base import Side
from lexarena.schemas.retrieval import CaseScope
from lexarena.schemas.statute_alias import StatuteAliasTable
from lexarena.storage.errors import AccessDeniedError
from lexarena.storage.policy import Principal, Role
from lexarena.storage.precedents import PrecedentRepository, ScopedPrecedentReader
from tests.fakes import WordEmbedder
from tests.test_precedent_prep import KNOWN, precedent, write_jsonl
from tests.test_precedent_store import clients, load  # noqa: F401  (fixture)
from tests.test_retrieval_tools import agent_view

pytestmark = pytest.mark.integration

CUTOFF = date(2005, 6, 1)


def records() -> list[dict[str, object]]:
    return [
        precedent("EARLY", decision_date="2001-01-01", statutes_cited=["TEST_ACT_SEC_7"]),
        precedent("DAY_BEFORE", decision_date="2005-05-31", statutes_cited=["TEST_ACT_2001_SEC_9"]),
        precedent("SAME_DAY", decision_date="2005-06-01"),
        precedent("LATER", decision_date="2010-01-01"),
        precedent("SHARED", decision_date="2002-01-01", case_title="<first case>"),
        precedent("SHARED", decision_date="2003-01-01", case_title="<second case, same precedent_id>"),
        precedent("EXCLUDED", decision_date="2002-06-01"),
    ]


@pytest.fixture
def loaded(tmp_path: Path, clients: tuple[QdrantClient, QdrantClient, str]) -> Iterator[tuple[QdrantClient, str]]:  # noqa: F811
    writer, reader, name = clients
    write_jsonl(tmp_path, "a.jsonl", records())
    load(tmp_path, PrecedentRepository(Principal(Role.INGEST), writer, name))
    yield reader, name


def scoped(
    reader: QdrantClient, name: str, role: Role = Role.LAWYER, excluded: tuple[str, ...] = ()
) -> ScopedPrecedentReader:
    side: Side | None = "PETITIONER" if role in (Role.LAWYER, Role.THEMIS_LOCAL) else None
    scope = CaseScope(decided_before=CUTOFF, excluded_precedent_ids=list(excluded))
    return ScopedPrecedentReader(Principal(role, side), reader, scope, name)


def ids(hits: list[tuple[dict[str, object], float]]) -> set[object]:
    return {p["precedent_id"] for p, _ in hits}


QUERY = WordEmbedder().embed(["<rule>"])[0]


def test_cut_off_is_strict_at_the_boundary(loaded: tuple[QdrantClient, str]) -> None:
    reader, name = loaded
    found = ids(scoped(reader, name).search("ratio", QUERY, [], 20))
    assert "DAY_BEFORE" in found and "EARLY" in found
    assert "SAME_DAY" not in found and "LATER" not in found


def test_facts_search_applies_the_same_scope(loaded: tuple[QdrantClient, str]) -> None:
    reader, name = loaded
    found = ids(scoped(reader, name, excluded=("EXCLUDED",)).search("facts", [QUERY], [], 20))
    assert found == {"EARLY", "DAY_BEFORE", "SHARED"}


def test_exclusion_by_precedent_id_removes_every_case_sharing_it(loaded: tuple[QdrantClient, str]) -> None:
    """Over-exclusion is the safe direction: a shared precedent_id hides both cases (D-024, SPEC B1)."""
    reader, name = loaded
    found = scoped(reader, name, excluded=("SHARED", "EXCLUDED")).search("ratio", QUERY, [], 20)
    assert ids(found) == {"EARLY", "DAY_BEFORE"}


def test_statute_filter_keeps_only_overlapping_precedents(loaded: tuple[QdrantClient, str]) -> None:
    reader, name = loaded
    found = scoped(reader, name).search("ratio", QUERY, ["TEST_ACT_2001_SEC_9"], 20)
    assert ids(found) == {"DAY_BEFORE"}


def test_get_refuses_later_and_excluded_precedents(loaded: tuple[QdrantClient, str]) -> None:
    reader, name = loaded
    everything = PrecedentRepository(Principal(Role.ORCHESTRATOR), reader, name).all_payloads()
    uid = {p["precedent_id"]: p["precedent_uid"] for p in everything if p["precedent_id"] != "SHARED"}
    r = scoped(reader, name, excluded=("EXCLUDED",))
    assert r.get(uid["EARLY"]) is not None
    assert r.get(uid["LATER"]) is None and r.get(uid["SAME_DAY"]) is None
    assert r.get(uid["EXCLUDED"]) is None
    assert r.get("<no such uid>") is None


@pytest.mark.parametrize("role", [Role.LAWYER, Role.THEMIS_LOCAL, Role.THEMIS_GLOBAL, Role.JUDGE])
def test_session_roles_have_no_unscoped_read(loaded: tuple[QdrantClient, str], role: Role) -> None:
    reader, name = loaded
    side: Side | None = "PETITIONER" if role in (Role.LAWYER, Role.THEMIS_LOCAL) else None
    repo = PrecedentRepository(Principal(role, side), reader, name)
    with pytest.raises(AccessDeniedError):
        repo.all_payloads()
    with pytest.raises(AccessDeniedError):
        repo.stored_hashes()


def test_tools_end_to_end_through_the_scoped_reader(loaded: tuple[QdrantClient, str]) -> None:
    reader, name = loaded
    tools = RetrievalTools(
        reader=scoped(reader, name, excluded=("EXCLUDED",)),
        case=agent_view(),
        embedder=WordEmbedder(),
        known_statutes=KNOWN,
        aliases=StatuteAliasTable(aliases=[]),
        top_k=10,
        query_instruction="<instruction> ",
    )
    for result in (tools.find_similar_cases("<deal>"), tools.find_authority("<rule>")):
        assert result.hits and all(h.decision_date < CUTOFF.isoformat() for h in result.hits)
        assert all(h.precedent_id != "EXCLUDED" for h in result.hits)
    later_uid = next(
        p["precedent_uid"]
        for p in PrecedentRepository(Principal(Role.ORCHESTRATOR), reader, name).all_payloads()
        if p["precedent_id"] == "LATER"
    )
    assert tools.get_precedent(later_uid) is None
