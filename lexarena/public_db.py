"""Runtime access to the public case DB (CLAUDE.md §6.6).

This module can only read `unspoiled.jsonl` and split lists. Ground truth and the manifest are
deliberately not reachable from here; the evaluator loads them separately after a transcript is sealed.
"""
import json
from pathlib import Path

from lexarena.schemas.public_case import PublicUnspoiled


class UnspoiledCase(PublicUnspoiled):
    def sections(self) -> dict:
        """The record as the agents' read_record tool serves it (JSON-ready)."""
        return self.model_dump(mode="json", exclude={"case_uid", "schema_version"})


class UnspoiledStore:
    FORBIDDEN = {"ground_truth.jsonl", "manifest.jsonl"}

    def __init__(self, public_db_dir: Path):
        self.dir = public_db_dir
        self._cases: dict[str, UnspoiledCase] | None = None

    def _load(self) -> dict[str, UnspoiledCase]:
        if self._cases is None:
            path = self.dir / "unspoiled.jsonl"
            if not path.exists():
                raise FileNotFoundError(f"{path} not found — build the public case DB first (CLAUDE.md §6.6, PB1–PB4)")
            self._cases = {}
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    case = UnspoiledCase.model_validate_json(line)
                    self._cases[case.case_uid] = case
        return self._cases

    def get(self, case_uid: str) -> UnspoiledCase:
        return self._load()[case_uid]

    def split(self, name: str) -> list[str]:
        path = self.dir / "splits" / f"{name}.txt"
        if not path.exists():
            raise FileNotFoundError(f"{path} not found")
        return [ln.strip() for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]


def retrieval_exclusions(public_db_dir: Path, case_uid: str) -> set[str]:
    """Reference-DB case_uids that are copies of this case (manifest.overlap_with_reference_db). Read by the
    orchestrator only; the manifest itself never reaches an agent. Belt and braces: the retrieval cutoff
    (strictly before the decision date) already excludes the case's own decision."""
    path = public_db_dir / "manifest.jsonl"
    if not path.exists():
        return set()
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rec = json.loads(line)
            if rec.get("case_uid") == case_uid:
                return set(rec.get("overlap_with_reference_db", {}).get("reference_case_uids", []))
    return set()


def to_json(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=1)
