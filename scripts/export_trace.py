"""Write the courtroom trace of a finished session from the database (D-110). Read-only on every store; free.

Sessions run before D-110 have no live trace. This rebuilds one from what was stored: the agent view, every published
turn with its THEMIS-LOCAL outcome, the global audit, every judge's decision, the bench verdict and the evaluation,
plus each logged model call with its cached answer (looked up by cache key; reasoning was not kept before D-110).
The result has the same format the session writes live, so the courtroom viewer shows old and new sessions alike.

Runs as the reflection role (private turns open only after the verdict), so only verdict-recorded sessions export.

    .venv/Scripts/python scripts/export_trace.py DEV_0007_DEV7_E2E_1_96aac1 [...]
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
from typing import Any

from lexarena.app import DEFAULT_ENV_FILE, REPO_ROOT, SEALED_ENV_FILE
from lexarena.config import load_config
from lexarena.schemas.base import SIDES
from lexarena.storage.factory import SealedProcess
from lexarena.trace import trace_path

CONFIG = REPO_ROOT / "config" / "config.v1.yaml"
PHASE_OF_ROLE = {"lawyer": "TURN", "verifier": "TURN", "extractor": "TURN", "auditor": "AUDIT", "judge": "BENCH"}


def _cached(db: sqlite3.Connection, key: str | None) -> Any:
    if not key:
        return None
    row = db.execute("SELECT text FROM responses WHERE key = ?", (key,)).fetchone()
    if row is None:
        return None
    try:
        return json.loads(row[0])
    except ValueError:
        return None


def export(proc: SealedProcess, session_id: str, log_path: Path, cache_path: Path, out_dir: Path) -> Path:
    stores = proc.reflection()
    session = stores.sessions.get(session_id)
    case = stores.cases.get(session.case_id).agent_view
    turns = stores.transcript.turns(session_id)
    private = {s: {p.turn: p for p in proc.reflection(s).private_turns.for_side(session_id, s)} for s in SIDES}

    records: list[dict[str, Any]] = []

    def add(kind: str, **data: Any) -> None:
        records.append({"seq": len(records), "session_id": session_id, "kind": kind, **data})

    add(
        "event",
        event="case_opened",
        ts=None,
        case_id=session.case_id,
        run_id=session_id.removeprefix(f"{session.case_id}_").rsplit("_", 1)[0],
        case_seq=session.case_seq,
        agent_view=case.model_dump(mode="json"),
        lessons={},
        judge_lessons=[],
        models={"lawyer": session.config.lawyer_model, "judge": session.config.judge_model},
        rebuilt=True,
    )
    db = sqlite3.connect(cache_path)
    calls = []
    for line in log_path.read_text(encoding="utf-8").splitlines():
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if e.get("session_id") == session_id:
            calls.append(e)
    # Model calls in the order they happened; published turns are placed after the calls that produced them.
    by_turn = {t.turn: t for t in turns}
    drafts_seen = 0
    plan: list[int] = sorted(by_turn)
    for e in calls:
        output = _cached(db, e.get("cache_key"))
        tags: dict[str, Any] = {"phase": PHASE_OF_ROLE.get(e["role"], "OTHER")}
        if e["schema"] in ("ResearchPlan", "StrategyNotes"):
            tags["phase"] = "PREPARE"
        add(
            "llm",
            ts=e["ts"],
            role=e["role"],
            schema=e["schema"],
            model=e["model"],
            provider=e["provider"],
            cached=e.get("outcome") == "cache_hit",
            input_tokens=e.get("input_tokens"),
            output_tokens=e.get("output_tokens"),
            latency_s=e.get("latency_s"),
            reasoning=None,
            output=output,
            error=e.get("error"),
            **tags,
        )
        if e["schema"] == "LawyerDraft":
            drafts_seen += 1
    for n in plan:
        t = by_turn[n]
        p = private[t.speaker].get(n)
        add(
            "event",
            event="turn_published",
            ts=t.created_at.isoformat(),
            phase="TURN",
            side=t.speaker,
            turn=n,
            turn_type=t.turn_type,
            published=t.model_dump(mode="json", by_alias=True),
            themis_local=p.themis_local.model_dump(mode="json") if p else None,
            claim_assessments=[a.model_dump(mode="json") for a in p.claim_assessments] if p else [],
        )
    if session.themis_global is not None:
        add("event", event="audit", ts=None, phase="AUDIT", report=session.themis_global.model_dump(mode="json"))
    for d in session.judge_decisions:
        add("event", event="judge_decision", ts=None, phase="BENCH", decision=d.model_dump(mode="json"))
    if session.bench is not None:
        add("event", event="verdict", ts=None, verdict=session.bench.model_dump(mode="json"), notes=[])
    if session.evaluation is not None:
        add("event", event="evaluation", ts=None, evaluation=session.evaluation.model_dump(mode="json"))
    if session.lessons_written:
        add("event", event="reflection", ts=None, written=session.lessons_written, updated=[], rejected=[])
    add("event", event="state", ts=None, state=session.state)

    path = trace_path(out_dir, session_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False, default=str) for r in records) + "\n", encoding="utf-8")
    return path


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("session_ids", nargs="+")
    args = ap.parse_args()
    cfg = load_config(CONFIG)
    with SealedProcess.from_env_files([DEFAULT_ENV_FILE, SEALED_ENV_FILE]) as proc:
        for sid in args.session_ids:
            path = export(
                proc, sid, REPO_ROOT / cfg.llm.log_path, REPO_ROOT / cfg.llm.cache_path, REPO_ROOT / cfg.llm.trace_dir
            )
            print(f"{sid}: {path} ({sum(1 for _ in path.open(encoding='utf-8'))} records)")


if __name__ == "__main__":
    main()
