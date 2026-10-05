"""Read-only data access for the viewer. No Streamlit here, so it can be unit-tested.

Never reads manifest.jsonl (real names). Ground truth is read only through `reveal_ground_truth`, which the
app calls only for a case that already has a verdict and only when the user asks.
"""
import json
import sqlite3
import time
from collections import defaultdict
from pathlib import Path

from lexarena.eval.ground_truth import load_ground_truth


def read_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def read_jsonl(path: Path, tail: int | None = None) -> list[dict]:
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    if tail:
        lines = lines[-tail:]
    out = []
    for line in lines:
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


# ---- runs on disk ----------------------------------------------------------------------------------------

def run_cases(runs_dir: Path) -> list[dict]:
    """Every runs/<run_id>/<case_uid>/ folder with what it contains, newest first."""
    rows = []
    if not runs_dir.exists():
        return rows
    for run in runs_dir.iterdir():
        if not run.is_dir():
            continue
        for case in run.iterdir():
            if case.is_dir():
                files = {p.name for p in case.iterdir()}
                mtime = max((p.stat().st_mtime for p in case.iterdir()), default=0)
                rows.append({"run_id": run.name, "case_uid": case.name, "transcript": "transcript.json" in files,
                             "verdict": "verdict.json" in files, "baseline": "baseline.json" in files, "mtime": mtime})
    return sorted(rows, key=lambda r: -r["mtime"])


def runs_with_metrics(runs_dir: Path) -> list[str]:
    return sorted(p.parent.name for p in runs_dir.glob("*/metrics.json")) if runs_dir.exists() else []


# ---- job queue (read-only) -------------------------------------------------------------------------------

def _ro(db: Path) -> sqlite3.Connection | None:
    if not db.exists():
        return None
    return sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)


def jobs(db: Path, kinds: tuple[str, ...] | None = None) -> list[dict]:
    con = _ro(db)
    if con is None:
        return []
    try:
        rows = con.execute("SELECT id, kind, key, payload, state, attempts, error, updated_at FROM jobs ORDER BY updated_at DESC").fetchall()
    finally:
        con.close()
    out = [{"id": r[0], "kind": r[1], "key": r[2], "payload": json.loads(r[3]), "state": r[4], "attempts": r[5],
            "error": r[6], "updated_at": r[7]} for r in rows]
    return [j for j in out if not kinds or j["kind"] in kinds]


def job_checkpoint(db: Path, key: str) -> dict:
    con = _ro(db)
    if con is None:
        return {}
    try:
        row = con.execute("SELECT checkpoint FROM jobs WHERE key=?", (key,)).fetchone()
    finally:
        con.close()
    return json.loads(row[0]) if row else {}


# ---- usage ledger and events -----------------------------------------------------------------------------

def windows(ledger_path: Path) -> dict:
    latest = {}
    for ev in read_jsonl(ledger_path):
        if ev.get("event") == "rate_limit":
            latest[ev.get("limit_type") or "unknown"] = ev
    now = time.time()
    out = {}
    for k, v in latest.items():
        expired = bool(v.get("resets_at")) and v["resets_at"] <= now
        out[k] = {"status": "reset (no calls since)" if expired else v.get("status"),
                  "utilization": None if expired else v.get("utilization"),
                  "resets_in_min": None if expired or not v.get("resets_at") else round((v["resets_at"] - now) / 60, 1)}
    return out


def usage_by_job(ledger_path: Path) -> list[dict]:
    agg: dict[tuple, dict] = defaultdict(lambda: {"calls": 0, "cached": 0, "cost_usd": 0.0, "output_tokens": 0})
    for ev in read_jsonl(ledger_path):
        if ev.get("event") != "call":
            continue
        a = agg[(ev.get("job") or "-", ev.get("role") or "-")]
        a["calls"] += 1
        a["cached"] += bool(ev.get("cached"))
        if not ev.get("cached"):
            a["cost_usd"] += ev.get("cost_usd") or 0.0
            a["output_tokens"] += (ev.get("usage") or {}).get("output_tokens", 0)
    return [{"job": j, "role": r, **v, "cost_usd": round(v["cost_usd"], 3)} for (j, r), v in sorted(agg.items())]


def events(state_dir: Path, job: str | None = None, tail: int = 400) -> list[dict]:
    evs = read_jsonl(state_dir / "events.jsonl", tail=tail)
    return [e for e in evs if job is None or e.get("job") == job]


def current_step(evs: list[dict]) -> str | None:
    """The step that has started but not finished (latest first)."""
    open_steps: dict[str, float] = {}
    for e in evs:
        if e["phase"] == "start":
            open_steps[e["step"]] = e["ts"]
        else:
            open_steps.pop(e["step"], None)
    return max(open_steps, key=open_steps.get) if open_steps else None


# ---- pipeline progress -----------------------------------------------------------------------------------

def pipeline_stages(checkpoint: dict, transcript: list[dict], verdict: dict | None, running_step: str | None,
                    total_turns: int = 5) -> list[dict]:
    """Stages for the progress strip: each turn, THEMIS-GLOBAL, the three judges, the verdict."""
    steps = set(checkpoint.get("steps", {}))
    done_turns = {t["turn"] for t in transcript}
    n_turns = max([total_turns] + list(done_turns))
    out = []
    for i in range(1, n_turns + 1):
        active = bool(running_step and running_step.startswith(f"turn_{i:02d}/"))
        out.append({"name": f"Turn {i}", "state": "done" if i in done_turns else "active" if active else "pending"})
    out.append({"name": "THEMIS-GLOBAL", "state": "done" if "global/report" in steps or verdict else
                "active" if running_step == "global/report" else "pending"})
    for p in ("textualist", "purposive", "proceduralist"):
        key = f"bench/{p}/draft"
        out.append({"name": p.capitalize(), "state": "done" if key in steps or verdict else
                    "active" if running_step and running_step.startswith(f"bench/{p}/") else "pending"})
    out.append({"name": "Verdict", "state": "done" if verdict else "pending"})
    return out


def gate_summary(turn: dict) -> list[dict]:
    """THEMIS-LOCAL log as a sequence of steps for display."""
    out = []
    for entry in turn.get("themis", {}).get("log", []):
        n = len(entry.get("findings", []))
        if entry.get("stage") == "A":
            out.append({"label": f"Stage A #{entry.get('attempt')}", "ok": n == 0, "findings": entry.get("findings", [])})
        else:
            out.append({"label": "Stage B", "ok": n == 0, "findings": entry.get("findings", [])})
    return out


# ---- case DBs ---------------------------------------------------------------------------------------------

def db_cases(db_dir: Path) -> list[dict]:
    """Unspoiled records (+ split) from a public case DB directory. Never the manifest."""
    path = db_dir / "unspoiled.jsonl"
    rows = read_jsonl(path) if path.exists() else ([read_json(db_dir / "unspoiled.json")] if (db_dir / "unspoiled.json").exists() else [])
    split_of = {}
    for sp in ("train", "dev", "test"):
        f = db_dir / "splits" / f"{sp}.txt"
        if f.exists():
            for uid in f.read_text(encoding="utf-8").split():
                split_of[uid] = sp
    for r in rows:
        r["_split"] = split_of.get(r["case_uid"], "-")
    return [r for r in rows if r]


def reveal_ground_truth(db_dir: Path, case_uid: str) -> dict | None:
    """Only for a case that already has a verdict (the app enforces that)."""
    return load_ground_truth(db_dir).get(case_uid)
