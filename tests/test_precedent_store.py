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

from lexarena.ingest.precedents import ingest_precedents, prepare_precedents, read_precedent_sources
from lexarena.secrets import SecretStore
from lexarena.storage.errors import AccessDeniedError
from lexarena.storage.policy import Principal, Role
from lexarena.storage.precedents import PrecedentRepository
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

    lawyer = PrecedentRepository(Principal(Role.LAWYER, "PETITIONER"), reader, name)
    assert lawyer.count() == 8  # P0 collides with another case: two points, not one

    by_uid = {r["precedent_id"] + r["case_title"]: r for r in records()}  # type: ignore[operator]
    for payload in random.Random(0).sample(lawyer.all_payloads(), 5):
        source = by_uid[payload["precedent_id"] + payload["case_title"]]
        assert {k: v for k, v in payload.items() if k in source} == source
        assert set(payload) - set(source) == {
            "precedent_uid", "statutes_normalized", "decision_date_ts", "content_hash", "source_file"
        }  # fmt: skip

    cutoff = date(2008, 1, 1)
    found = lawyer.search_ratio(WordEmbedder().embed(["<rule>"])[0], decided_before=cutoff, exclude_ids=[], limit=20)
    assert found and all(p["decision_date"] < cutoff.isoformat() for p in found)
    excluded = lawyer.search_ratio(
        WordEmbedder().embed(["<rule>"])[0], decided_before=cutoff, exclude_ids=["P1"], limit=20
    )
    assert "P1" not in {p["precedent_id"] for p in excluded} and len(excluded) == len(found) - 1

    again = load(tmp_path, ingest_repo)
    assert (again.inserted, again.updated, again.removed, again.unchanged) == (0, 0, 0, 8)  # type: ignore[attr-defined]
    assert again.snapshot == first.snapshot  # type: ignore[attr-defined]


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
    with pytest.raises(AccessDeniedError):
        PrecedentRepository(Principal(Role.LAWYER, "PETITIONER"), reader, name).delete(["x"])
    # The read-only key is refused by Qdrant itself, whatever the Python role says.
    with pytest.raises(Exception, match=r"(?i)forbidden|403"):
        PrecedentRepository(Principal(Role.INGEST), reader, name).delete([str(uuid.uuid4())])
