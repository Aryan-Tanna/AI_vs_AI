"""Sealed ground truth loader. Imported only by the evaluator (and, later, train-split reflection); runtime agents
and their tools never import this module (tests check that)."""
import json
from pathlib import Path


def load_ground_truth(public_db_dir: Path) -> dict[str, dict]:
    path = public_db_dir / "ground_truth.jsonl"
    if not path.exists():
        return {}
    return {r["case_uid"]: r for r in (json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip())}
