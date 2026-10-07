"""BUILD_PLAN Step 2 against the real MongoDB: loading is validated and idempotent, only APPROVED overlay rows
are stored, and get_statute hides a section on dates it is not in force.

The real Law DB files are loaded as they are; overlay rows are attached only to a synthetic placeholder
statute, so no test encodes a rule about real law (non-negotiable 8).

Run with: pytest --run-integration -m integration
"""

from __future__ import annotations

import json
import shutil
import uuid
from collections.abc import Iterator
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from lexarena.ingest.law_db import LawDbNotLoadableError, load_law_db, read_law_sources, validate_law_db
from lexarena.schemas.base import Side
from lexarena.schemas.overlay import TemporalOverlayRow
from lexarena.secrets import SecretStore
from lexarena.storage.errors import AccessDeniedError
from lexarena.storage.factory import SealedProcess, SessionProcess
from lexarena.storage.law import LawRepository, OverlayRejectedError
from lexarena.storage.mongo import Namespace
from lexarena.storage.policy import Principal, Role
from lexarena.storage.temporal import AsOf
from tests.conftest import ENV_FILE, REPO_ROOT, SEALED_ENV_FILE
from tests.test_law_validation import law_record

pytestmark = pytest.mark.integration
LAW_DIR = REPO_ROOT / "data" / "law_db"
SYNTHETIC = "TEST_ACT_SEC_1"


class Procs:
    def __init__(self) -> None:
        self.ns = Namespace(prefix=f"t{uuid.uuid4().hex[:8]}_")
        self.session = SessionProcess(SecretStore(env_file=[ENV_FILE], environ={}), self.ns)
        self.offline = SealedProcess(SecretStore(env_file=[ENV_FILE, SEALED_ENV_FILE], environ={}), self.ns)

    def close(self) -> None:
        db = self.session._app_db
        for name in db.list_collection_names():
            if name.startswith(self.ns.prefix):
                db.drop_collection(name)
        self.session.close()
        self.offline.close()


@pytest.fixture
def procs() -> Iterator[Procs]:
    p = Procs()
    yield p
    p.close()


def overlay(overlay_id: str, value: Any, start: str | None, end: str | None, **kw: Any) -> TemporalOverlayRow:
    base: dict[str, Any] = {
        "overlay_id": overlay_id,
        "statute_id": SYNTHETIC,
        "parameter": "section_in_force",
        "value": value,
        "keyed_on": "FILING",
        "effective_from": start,
        "effective_to": end,
        "source_ref": "<ref>",
        "source_text": "<text>",
        "status": "APPROVED",
        "approved_by": "<reviewer>",
        "version": 1,
    }
    return TemporalOverlayRow.model_validate({**base, **kw})


def synthetic_source(tmp_path: Path) -> Path:
    folder = tmp_path / "law"
    folder.mkdir()
    (folder / "synthetic.json").write_text(json.dumps([law_record(SYNTHETIC)]), encoding="utf-8")
    return folder


# ---------------------------------------------------------------- loading


def test_real_law_db_loads_every_valid_record_and_reload_changes_nothing(procs: Procs) -> None:
    ingest = procs.offline.ingest()
    report = validate_law_db(*read_law_sources(LAW_DIR))
    first = load_law_db(ingest.law, report)
    assert first.inserted == report.valid and first.updated == first.removed == 0
    assert ingest.law.snapshot() == report.snapshot == first.snapshot

    second = load_law_db(ingest.law, validate_law_db(*read_law_sources(LAW_DIR)))
    assert (second.inserted, second.updated, second.removed, second.unchanged) == (0, 0, 0, report.valid)
    assert second.snapshot == first.snapshot


def test_reload_applies_edits_and_removals(procs: Procs, tmp_path: Path) -> None:
    source = tmp_path / "law"
    shutil.copytree(LAW_DIR, source)
    ingest = procs.offline.ingest()
    before = load_law_db(ingest.law, validate_law_db(*read_law_sources(source)))

    target = sorted(source.glob("*.json"))[0]
    records = json.loads(target.read_text(encoding="utf-8"))
    removed_id = records[0]["_id"]
    records[1]["section_title"] = "<edited title>"
    target.write_text(json.dumps(records[1:], indent=2), encoding="utf-8")

    after = load_law_db(ingest.law, validate_law_db(*read_law_sources(source)))
    assert (after.updated, after.removed, after.inserted) == (1, 1, 0)
    assert after.snapshot != before.snapshot
    assert procs.session.lawyer("PETITIONER", "S").law.get_statute(removed_id, AsOf(key_dates={})) is None


def test_unloadable_source_is_refused_and_leaves_the_db_unchanged(procs: Procs, tmp_path: Path) -> None:
    ingest = procs.offline.ingest()
    load_law_db(ingest.law, validate_law_db(*read_law_sources(synthetic_source(tmp_path))))
    snapshot = ingest.law.snapshot()
    broken = tmp_path / "broken"
    broken.mkdir()
    bad = law_record("TEST_ACT_SEC_2")
    del bad["statute_id"]
    (broken / "a.json").write_text(json.dumps([bad]), encoding="utf-8")
    with pytest.raises(LawDbNotLoadableError):
        load_law_db(ingest.law, validate_law_db(*read_law_sources(broken)))
    assert ingest.law.snapshot() == snapshot


@pytest.mark.parametrize("role", [Role.LAWYER, Role.THEMIS_LOCAL, Role.JUDGE, Role.ORCHESTRATOR, Role.CLERK])
def test_only_ingestion_writes_the_law_db(procs: Procs, tmp_path: Path, role: Role) -> None:
    side: Side | None = "PETITIONER" if role in (Role.LAWYER, Role.THEMIS_LOCAL) else None
    repo = LawRepository(Principal(role, side), procs.session._app_db, procs.ns)
    report = validate_law_db(*read_law_sources(synthetic_source(tmp_path)))
    with pytest.raises(AccessDeniedError):
        load_law_db(repo, report)
    with pytest.raises(AccessDeniedError):
        repo.put_overlay(overlay("ov", True, None, None))


# ---------------------------------------------------------------- get_statute with approved overlay rows


def test_get_statute_hides_a_section_before_it_is_in_force(procs: Procs, tmp_path: Path) -> None:
    ingest = procs.offline.ingest()
    load_law_db(ingest.law, validate_law_db(*read_law_sources(synthetic_source(tmp_path))))
    lawyer = procs.session.lawyer("PETITIONER", "S").law

    unverified = lawyer.get_statute(SYNTHETIC, AsOf(key_dates={"FILING": date(2000, 6, 1)}))
    assert unverified is not None and unverified.in_force == "UNVERIFIED"

    ingest.law.put_overlay(overlay("ov-in-force", True, "2001-01-01", None))
    assert lawyer.get_statute(SYNTHETIC, AsOf(key_dates={"FILING": date(2000, 12, 31)})) is None
    confirmed = lawyer.get_statute(SYNTHETIC, AsOf(key_dates={"FILING": date(2001, 1, 1)}))
    assert confirmed is not None and confirmed.in_force == "CONFIRMED"
    assert [a.overlay_id for a in confirmed.applied] == ["ov-in-force"]


def test_hidden_and_unknown_statutes_look_the_same(procs: Procs, tmp_path: Path) -> None:
    ingest = procs.offline.ingest()
    load_law_db(ingest.law, validate_law_db(*read_law_sources(synthetic_source(tmp_path))))
    ingest.law.put_overlay(overlay("ov", True, "2001-01-01", None))
    lawyer = procs.session.lawyer("PETITIONER", "S").law
    as_of = AsOf(key_dates={"FILING": date(2000, 1, 1)})
    assert lawyer.get_statute(SYNTHETIC, as_of) is None
    assert lawyer.get_statute("TEST_NO_SUCH_SECTION", as_of) is None


@pytest.mark.parametrize(
    ("row", "message"),
    [
        (overlay("ov", True, None, None, status="DRAFT", approved_by=None), "only APPROVED"),
        (overlay("ov", True, None, None, statute_id="TEST_NOT_IN_LAW_DB"), "not in the Law DB"),
    ],
)
def test_overlay_rows_must_be_approved_and_attached(
    procs: Procs, tmp_path: Path, row: TemporalOverlayRow, message: str
) -> None:
    ingest = procs.offline.ingest()
    load_law_db(ingest.law, validate_law_db(*read_law_sources(synthetic_source(tmp_path))))
    with pytest.raises(OverlayRejectedError, match=message):
        ingest.law.put_overlay(row)


def test_overlapping_overlay_rows_are_rejected(procs: Procs, tmp_path: Path) -> None:
    ingest = procs.offline.ingest()
    load_law_db(ingest.law, validate_law_db(*read_law_sources(synthetic_source(tmp_path))))
    ingest.law.put_overlay(overlay("a", True, "2001-01-01", None))
    with pytest.raises(OverlayRejectedError, match="overlaps"):
        ingest.law.put_overlay(overlay("b", False, "2005-01-01", None))
    ingest.law.put_overlay(overlay("a", True, "2001-01-01", "2004-12-31", version=2))  # replacing by ID is allowed
    ingest.law.put_overlay(overlay("b", False, "2005-01-01", None))
    lawyer = procs.session.lawyer("PETITIONER", "S").law
    assert lawyer.get_statute(SYNTHETIC, AsOf(key_dates={"FILING": date(2006, 1, 1)})) is None


def test_decision_keyed_rows_never_reveal_the_simulation_date(procs: Procs, tmp_path: Path) -> None:
    """D-035: no session-role read returns the decision date, even through an overlay keyed on it."""
    from tests import builders

    sentinel_date = "1999-12-31"  # literal-ok: sentinel simulation_date
    ingest = procs.offline.ingest()
    load_law_db(ingest.law, validate_law_db(*read_law_sources(synthetic_source(tmp_path))))
    ingest.law.put_overlay(overlay("ov-decision", True, "1990-01-01", None, keyed_on="DECISION"))
    as_of = AsOf.for_case(builders.case("TESTCASE_0001", date_marker=sentinel_date))
    view = procs.session.lawyer("PETITIONER", "S").law.get_statute(SYNTHETIC, as_of)
    assert view is not None and view.in_force == "CONFIRMED"  # positive control: the row was applied
    assert sentinel_date not in view.model_dump_json()
