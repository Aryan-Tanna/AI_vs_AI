"""BUILD_PLAN Step 3 acceptance against the real MongoDB: only APPROVED drafts load, every quote and the
source hash are re-verified at load, and a changed Law DB item marks its predicate STALE.

Synthetic Test Act and placeholder statute only; nothing here is law.

Run with: pytest --run-integration -m integration
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from lexarena.config import load_config
from lexarena.drafting.draft import draft_overlay, draft_predicate
from lexarena.drafting.loader import load_approved
from lexarena.drafting.review import ReviewStore
from lexarena.drafting.sources import SourceRegistry
from lexarena.ingest.law_db import load_law_db, read_law_sources, validate_law_db
from lexarena.prompts import PromptStore
from lexarena.schemas.config import AppConfig
from lexarena.schemas.law import LawRecord
from lexarena.storage.errors import AccessDeniedError
from lexarena.storage.law import LawRepository, PredicateRejectedError
from lexarena.storage.policy import Principal, Role
from lexarena.storage.temporal import AsOf
from tests.conftest import CONFIG_V1, PROMPTS_ROOT
from tests.test_drafting import IN_FORCE, STATUTE, client, predicate_proposal, proposal
from tests.test_drafting_sources import TEST_TEXT, make_pdf, meta
from tests.test_law_repository import Procs
from tests.test_law_validation import law_record

pytestmark = pytest.mark.integration
ITEM = "<prerequisite with a period of thirty days>"


@pytest.fixture
def cfg() -> AppConfig:
    return load_config(CONFIG_V1)


@pytest.fixture
def procs() -> Iterator[Procs]:
    p = Procs()
    yield p
    p.close()


class World:
    def __init__(self, tmp: Path, procs: Procs, cfg: AppConfig) -> None:
        self.cfg, self.procs = cfg, procs
        self.registry = SourceRegistry(tmp / "sources")
        self.registry.register(make_pdf(TEST_TEXT), meta())
        self.store = ReviewStore(tmp / "review")
        self.law_dir = tmp / "law"
        self.law_dir.mkdir()
        self.items = [ITEM]
        self.ingest = procs.offline.ingest().law
        self.reload_law()

    def record_raw(self) -> dict[str, Any]:
        raw = law_record(STATUTE)
        raw["diagnostic_checklist"]["mandatory_prerequisites"] = list(self.items)
        return raw

    def reload_law(self) -> Any:
        (self.law_dir / "a.json").write_text(json.dumps([self.record_raw()]), encoding="utf-8")
        return load_law_db(self.ingest, validate_law_db(*read_law_sources(self.law_dir)))

    def record(self) -> LawRecord:
        return LawRecord.model_validate(self.record_raw())

    def draft_overlay(self, row: dict[str, Any]) -> str:
        llm, _, _ = client(self.cfg, proposal(row), proposal(row))
        [d] = draft_overlay(
            llm, self.cfg, PromptStore(PROMPTS_ROOT), self.record(), self.registry, "TEST_ACT_2001", ["99X"]
        )
        self.store.save(d)
        return d.draft_id

    def draft_predicate(self) -> str:
        llm, _, _ = client(self.cfg, predicate_proposal(), predicate_proposal())
        [d] = draft_predicate(
            llm, self.cfg, PromptStore(PROMPTS_ROOT), self.record(), self.registry, "TEST_ACT_2001", ["99X"]
        )
        self.store.save(d)
        return d.draft_id

    def load(self) -> Any:
        return load_approved(self.store, self.registry, self.ingest, self.cfg.vocabulary)

    def lawyer(self) -> LawRepository:
        return self.procs.session.lawyer("PETITIONER", "S").law


@pytest.fixture
def world(tmp_path: Path, procs: Procs, cfg: AppConfig) -> World:
    return World(tmp_path, procs, cfg)


def test_only_approved_drafts_load(world: World) -> None:
    approved = world.draft_overlay(IN_FORCE)
    rejected = world.draft_overlay({**IN_FORCE, "keyed_on": "DEFAULT"})
    pending = world.draft_overlay({**IN_FORCE, "keyed_on": "ADMISSION"})
    world.store.approve(approved, by="<reviewer>")
    world.store.reject(rejected, by="<reviewer>", reason="<wrong date>")

    report = world.load()
    assert report.loaded == [approved] and report.skipped == {}
    assert report.not_approved == 2 and pending not in report.loaded

    before = world.lawyer().get_statute(STATUTE, AsOf(key_dates={"DECISION": date(2001, 6, 4)}))
    after = world.lawyer().get_statute(STATUTE, AsOf(key_dates={"DECISION": date(2001, 6, 5)}))
    assert before is None
    assert after is not None and after.in_force == "CONFIRMED" and after.applied[0].overlay_id == approved


def test_changed_source_blocks_loading(world: World, tmp_path: Path) -> None:
    approved = world.draft_overlay(IN_FORCE)
    world.store.approve(approved, by="<reviewer>")
    text_file = tmp_path / "sources" / world.registry.get("TEST_ACT_2001").text_file
    text_file.write_text(text_file.read_text(encoding="utf-8") + " ", encoding="utf-8")
    report = world.load()
    assert report.loaded == [] and "no longer match" in report.skipped[approved]


def test_hand_approved_draft_with_blocking_problems_is_refused(world: World, tmp_path: Path) -> None:
    bad = world.draft_overlay({**IN_FORCE, "source_text": "<not in the source>"})
    path = tmp_path / "review" / "temporal_overlay" / f"{bad}.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc.update(status="APPROVED", decided_by="<reviewer>", decided_on="2001-01-01", blocking_problems=[])
    path.write_text(json.dumps(doc), encoding="utf-8")  # bypassing the CLI guard
    report = world.load()
    assert report.loaded == [] and "not found verbatim" in report.skipped[bad]


def test_approved_predicate_loads_and_goes_stale_when_its_item_changes(world: World) -> None:
    pid = world.draft_predicate()
    world.store.approve(pid, by="<reviewer>")
    assert world.load().loaded == [pid]
    [stored] = world.lawyer().predicates(STATUTE)
    assert (stored.status, stored.approved_by, stored.item_index) == ("APPROVED", "<reviewer>", 0)

    world.items = ["<a new first item>", ITEM]  # the same text moves: still approved, index follows it
    assert world.reload_law().stale_predicates == []
    [moved] = world.lawyer().predicates(STATUTE)
    assert moved.item_index == 1

    world.items = ["<a new first item>", ITEM + " <edited>"]  # the text itself changes: STALE
    assert world.reload_law().stale_predicates == [pid]
    assert world.lawyer().predicates(STATUTE) == []  # stale predicates are never served

    world.items = [ITEM]  # the approved text is back: approved again
    world.reload_law()
    assert [p.predicate_id for p in world.lawyer().predicates(STATUTE)] == [pid]


def test_predicate_drafted_against_old_text_is_refused_at_load(world: World) -> None:
    pid = world.draft_predicate()
    world.store.approve(pid, by="<reviewer>")
    world.items = [ITEM + " <edited>"]
    world.reload_law()
    report = world.load()
    assert report.loaded == [] and "changed since" in report.skipped[pid]


@pytest.mark.parametrize("role", [Role.LAWYER, Role.JUDGE, Role.CLERK, Role.REFLECTION])
def test_only_ingestion_writes_predicates(world: World, role: Role) -> None:
    pid = world.draft_predicate()
    entry = world.store.get(pid).entry  # type: ignore[union-attr]
    assert entry is not None
    side = "PETITIONER" if role == Role.LAWYER else None
    repo = LawRepository(Principal(role, side), world.procs.session._app_db, world.procs.ns)  # type: ignore[arg-type]
    with pytest.raises(AccessDeniedError):
        repo.put_predicate(entry.model_copy(update={"status": "APPROVED", "approved_by": "<reviewer>"}))


def test_put_predicate_refuses_drafts(world: World) -> None:
    pid = world.draft_predicate()
    entry = world.store.get(pid).entry  # type: ignore[union-attr]
    assert entry is not None
    with pytest.raises(PredicateRejectedError, match="only APPROVED"):
        world.ingest.put_predicate(entry)


def test_source_re_pinned_after_drafting_blocks_loading(world: World, tmp_path: Path) -> None:
    """The registry was updated (new text, hashes consistent) after the item was drafted from the old text."""
    import hashlib

    approved = world.draft_overlay(IN_FORCE)
    world.store.approve(approved, by="<reviewer>")
    root = tmp_path / "sources"
    entries = json.loads((root / "registry.json").read_text(encoding="utf-8"))
    text_path = root / entries[0]["text_file"]
    new_text = text_path.read_bytes() + b"\n<re-extracted>"
    text_path.write_bytes(new_text)
    entries[0]["text_sha256"] = hashlib.sha256(new_text).hexdigest()
    (root / "registry.json").write_text(json.dumps(entries), encoding="utf-8")
    world.registry = SourceRegistry(root)
    report = world.load()
    assert report.loaded == [] and "differs from the version" in report.skipped[approved]
