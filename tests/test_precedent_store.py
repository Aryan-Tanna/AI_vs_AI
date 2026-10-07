"""BUILD_PLAN Step 4 acceptance against the real Qdrant, with a fast fake embedder and placeholder records.

Run with: pytest --run-integration -m integration
"""

from __future__ import annotations

import random
import uuid
from collections.abc import Iterator
from datetime import date
from pathlib import Path

import pytest
from qdrant_client import QdrantClient

from lexarena.ingest.precedents import DERIVED_FIELDS, ingest_precedents, prepare_precedents, read_precedent_sources
from lexarena.schemas.retrieval import CaseScope
from lexarena.secrets import SecretStore
from lexarena.storage.errors import AccessDeniedError
from lexarena.storage.policy import Principal, Role
from lexarena.storage.precedents import PrecedentRepository, ScopedPrecedentReader
from tests.conftest import ENV_FILE, SEALED_ENV_FILE
from tests.fakes import WordEmbedder
from tests.test_precedent_prep import KNOWN, precedent, write_jsonl

pytestmark = pytest.mark.integration


@pytest.fixture
def clients() -> Iterator[tuple[QdrantClient, QdrantClient, str]]:
    secrets = SecretStore(env_file=[ENV_FILE, SEALED_ENV_FILE], environ={})
    url = secrets.get("LEXARENA_QDRANT_URL")
    writer = QdrantClient(url=url, api_key=secrets.get("LEXARENA_QDRANT_WRITE_API_KEY"), https=False)
    reader = QdrantClient(url=url, api_key=secrets.get("LEXARENA_QDRANT_READ_ONLY_API_KEY"), https=False)
    name = f"t{uuid.uuid4().hex[:8]}_precedents"
    yield writer, reader, name
    if writer.collection_exists(name):
        writer.delete_collection(name)


def records() -> list[dict[str, object]]:
    years = [2001, 2003, 2005, 2007, 2009, 2011, 2013]
    out = [precedent(f"P{i}", decision_date=f"{y}-06-01", case_title=f"<case {i}>") for i, y in enumerate(years)]
    out.append(precedent("P0", decision_date="2015-01-01", case_title="<another case with a colliding id>"))
    return out


def load(folder: Path, repo: PrecedentRepository) -> object:
    prepared = prepare_precedents(*read_precedent_sources(folder), KNOWN, WordEmbedder(), window_tokens=50)
    return ingest_precedents(repo, prepared, WordEmbedder())


def test_count_payloads_dates_and_rerun(tmp_path: Path, clients: tuple[QdrantClient, QdrantClient, str]) -> None:
    writer, reader, name = clients
    write_jsonl(tmp_path, "a.jsonl", records())
    ingest_repo = PrecedentRepository(Principal(Role.INGEST), writer, name)
    first = load(tmp_path, ingest_repo)
    assert (first.inserted, first.updated, first.removed) == (8, 0, 0)  # type: ignore[attr-defined]

    orchestrator = PrecedentRepository(Principal(Role.ORCHESTRATOR), reader, name)
    assert orchestrator.count() == 8  # P0 collides with another case: two points, not one

    by_uid = {r["precedent_id"] + r["case_title"]: r for r in records()}  # type: ignore[operator]
    for payload in random.Random(0).sample(orchestrator.all_payloads(), 5):
        source = by_uid[payload["precedent_id"] + payload["case_title"]]
        assert {k: v for k, v in payload.items() if k in source} == source
        assert set(payload) - set(source) == DERIVED_FIELDS

    cutoff = date(2008, 1, 1)
    query = WordEmbedder().embed(["<rule>"])[0]
    lawyer = Principal(Role.LAWYER, "PETITIONER")
    open_scope = CaseScope(decided_before=cutoff, excluded_precedent_ids=[])
    found = ScopedPrecedentReader(lawyer, reader, open_scope, name).search("ratio", query, [], 20)
    assert found and all(p["decision_date"] < cutoff.isoformat() for p, _ in found)
    p1_out = CaseScope(decided_before=cutoff, excluded_precedent_ids=["P1"])
    excluded = ScopedPrecedentReader(lawyer, reader, p1_out, name).search("ratio", query, [], 20)
    assert "P1" not in {p["precedent_id"] for p, _ in excluded} and len(excluded) == len(found) - 1

    again = load(tmp_path, ingest_repo)
    assert (again.inserted, again.updated, again.removed, again.unchanged) == (0, 0, 0, 8)  # type: ignore[attr-defined]
    assert again.snapshot == first.snapshot  # type: ignore[attr-defined]


def test_derived_field_changes_refresh_payloads_without_re_embedding(
    tmp_path: Path, clients: tuple[QdrantClient, QdrantClient, str]
) -> None:
    """The Law DB grows after ingestion: statutes_normalized must follow, though no record changed."""
    writer, _, name = clients
    repo = PrecedentRepository(Principal(Role.INGEST), writer, name)
    write_jsonl(tmp_path, "a.jsonl", [precedent("P1", statutes_cited=["TEST_ACT_SEC_7", "TEST_ACT_SEC_8"])])
    first = ingest_precedents(
        repo, prepare_precedents(*read_precedent_sources(tmp_path), KNOWN, WordEmbedder(), window_tokens=50),
        WordEmbedder(),
    )  # fmt: skip
    grown = prepare_precedents(
        *read_precedent_sources(tmp_path), KNOWN | {"TEST_ACT_SEC_8"}, WordEmbedder(), window_tokens=50
    )
    embedder = WordEmbedder()
    second = ingest_precedents(repo, grown, embedder)
    assert (second.inserted, second.updated, second.payload_refreshed) == (0, 0, 1)
    assert embedder.calls == 0
    [payload] = repo.all_payloads()
    assert payload["statutes_normalized"] == ["TEST_ACT_SEC_7", "TEST_ACT_SEC_8"]
    assert second.snapshot != first.snapshot
    third = ingest_precedents(repo, grown, WordEmbedder())
    assert (third.payload_refreshed, third.unchanged) == (0, 1)


def test_edits_and_removals_are_incremental(tmp_path: Path, clients: tuple[QdrantClient, QdrantClient, str]) -> None:
    writer, _, name = clients
    repo = PrecedentRepository(Principal(Role.INGEST), writer, name)
    write_jsonl(tmp_path, "a.jsonl", records())
    load(tmp_path, repo)
    changed = records()[1:]
    changed[0] = {**changed[0], "summary": "<edited summary>"}
    write_jsonl(tmp_path, "a.jsonl", changed)
    result = load(tmp_path, repo)
    assert (result.inserted, result.updated, result.removed) == (0, 1, 1)  # type: ignore[attr-defined]
    assert repo.count() == 7


def test_session_roles_cannot_write_and_judges_cannot_search_openly(
    tmp_path: Path, clients: tuple[QdrantClient, QdrantClient, str]
) -> None:
    writer, reader, name = clients
    write_jsonl(tmp_path, "a.jsonl", records())
    load(tmp_path, PrecedentRepository(Principal(Role.INGEST), writer, name))
    for role in (Role.LAWYER, Role.THEMIS_LOCAL, Role.JUDGE):
        repo = PrecedentRepository(Principal(role, "PETITIONER" if role is not Role.JUDGE else None), reader, name)
        with pytest.raises(AccessDeniedError):
            repo.delete(["x"])
        with pytest.raises(AccessDeniedError):
            repo.overwrite_payload(str(uuid.uuid4()), {"x": 1})
    with pytest.raises(Exception, match=r"(?i)forbidden|403"):
        PrecedentRepository(Principal(Role.INGEST), reader, name).overwrite_payload(str(uuid.uuid4()), {"x": 1})
    # The read-only key is refused by Qdrant itself, whatever the Python role says.
    with pytest.raises(Exception, match=r"(?i)forbidden|403"):
        PrecedentRepository(Principal(Role.INGEST), reader, name).delete([str(uuid.uuid4())])
