"""`lexarena run ...`: the run manager (BUILD_PLAN Step 13; D-073).

    lexarena run plan RUN_ID --mode LEARN|FROZEN|EMPTY [--split DEV] [--case-id ID ...] [--ablation A ...] [--dry-run]
    lexarena run go RUN_ID [--max-cases N]      execute or resume (spends LLM quota unless the run is a dry run)
    lexarena run status RUN_ID
    lexarena run report RUN_ID                  writes <runs_dir>/<RUN_ID>/report.json and report.md

The run manager holds session credentials only (it reads the case index through the orchestrator role). Each stage
is a separate `lexarena` process; the evaluator's process loads the sealed credentials itself (D-034).
"""

from __future__ import annotations

import argparse
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from lexarena.app import DEFAULT_ENV_FILE, REPO_ROOT
from lexarena.config import config_sha256, load_config
from lexarena.runner.ledger import LedgerStore
from lexarena.runner.manager import RunManager, new_job
from lexarena.runner.memory import NoMemory
from lexarena.runner.plan import CaseRef, PlanRefusedError, check_plan, run_order
from lexarena.runner.quota import usage_since, window_start
from lexarena.runner.report import build_report, to_markdown
from lexarena.runner.stages import DEFAULT_SPECS, SubprocessExecutor
from lexarena.schemas.case import Split
from lexarena.schemas.config import AppConfig
from lexarena.schemas.run import STAGES, MemoryMode, RunLedger, RunManifest
from lexarena.storage.factory import SessionProcess

JSON_INDENT = 2  # literal-ok: display indentation


def add_parsers(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    run = sub.add_parser("run").add_subparsers(dest="action", required=True)
    plan = run.add_parser("plan", help="create a run: cases in date order, mode, ablations")
    plan.add_argument("run_id")
    plan.add_argument("--mode", choices=["LEARN", "FROZEN", "EMPTY"], required=True)
    plan.add_argument("--split", action="append", help="include cases of this split (repeatable; default DEV)")
    plan.add_argument("--case-id", action="append", help="only these cases (repeatable)")
    plan.add_argument("--ablation", action="append", default=[], help="an ablation switch from runner.ablations")
    plan.add_argument("--dry-run", action="store_true", help="plan and record every stage without executing")
    go = run.add_parser("go", help="execute or resume a run (spends LLM quota)")
    go.add_argument("run_id")
    go.add_argument("--max-cases", type=int)
    for name in ("status", "report"):
        run.add_parser(name).add_argument("run_id")


def git_sha() -> str:
    def git(*args: str) -> str:
        done = subprocess.run(["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, check=False)
        return done.stdout.strip()

    sha = git("rev-parse", "HEAD") or "unknown"
    return f"{sha}-dirty" if git("status", "--porcelain", "--untracked-files=no") else sha


def _store(cfg: AppConfig, run_id: str) -> LedgerStore:
    return LedgerStore(REPO_ROOT / cfg.runner.runs_dir, run_id)


def _plan(args: argparse.Namespace, cfg: AppConfig, config_path: Path) -> int:
    store = _store(cfg, args.run_id)
    if store.exists():
        raise SystemExit(f"run {args.run_id} already exists; plan a new run ID")
    unknown = sorted(set(args.ablation) - set(cfg.runner.ablations))
    if unknown:
        raise SystemExit(f"unknown ablations {unknown}; allowed: {cfg.runner.ablations}")
    splits = set(args.split or ["DEV"])
    with SessionProcess.from_env_files([DEFAULT_ENV_FILE]) as proc:
        index = proc.orchestrator().cases.index()
    refs = [CaseRef(cid, cast(Split, split), day) for cid, split, day in index if split in splits]
    if args.case_id:
        missing = sorted(set(args.case_id) - {r.case_id for r in refs})
        if missing:
            raise SystemExit(f"cases not found in the chosen splits: {missing}")
        refs = [r for r in refs if r.case_id in set(args.case_id)]
    mode = cast(MemoryMode, args.mode)
    try:
        check_plan(refs, mode, cfg.runner, sorted(splits))
    except PlanRefusedError as exc:
        raise SystemExit(str(exc)) from exc
    ordered = run_order(refs)
    ledger = RunLedger(
        manifest=RunManifest(
            run_id=args.run_id,
            created_at=datetime.now(UTC),
            mode=mode,
            ablations=args.ablation,
            stages=list(STAGES),
            git_sha=git_sha(),
            config_version=cfg.version,
            config_sha256=config_sha256(config_path),
            dry_run=args.dry_run,
        ),
        status="PLANNED",
        pause_reason=None,
        jobs=[new_job(n, r.case_id, r.split, r.decided_on, list(STAGES)) for n, r in enumerate(ordered, 1)],
    )
    store.save(ledger)
    print(json.dumps({"run_id": args.run_id, "mode": mode, "cases": [r.case_id for r in ordered]}))
    return 0


def _quota_used(cfg: AppConfig) -> dict[str, dict[str, int]]:
    used = usage_since(REPO_ROOT / cfg.llm.log_path, cfg, window_start(datetime.now(UTC), cfg))
    return {f"{m} on {k}": {"requests": u.requests, "tokens": u.tokens} for (m, k), u in sorted(used.items())}


def _status(ledger: RunLedger) -> dict[str, object]:
    return {
        "run_id": ledger.manifest.run_id,
        "status": ledger.status,
        "pause_reason": ledger.pause_reason,
        "cases": {j.case_id: {r.stage: r.status for r in j.stages} for j in ledger.jobs},
    }


def run(args: argparse.Namespace, config_path: Path) -> int:
    cfg = load_config(config_path)
    if args.action == "plan":
        return _plan(args, cfg, config_path)
    store = _store(cfg, args.run_id)
    if not store.exists():
        raise SystemExit(f"no run {args.run_id}; plan it first")
    if args.action == "go":
        manager = RunManager(
            cfg,
            store,
            DEFAULT_SPECS,
            SubprocessExecutor(config_path, REPO_ROOT, cfg.runner.stage_timeout_s),
            NoMemory(),
            REPO_ROOT / cfg.llm.log_path,
        )
        ledger = manager.go(max_cases=args.max_cases)
        print(json.dumps(_status(ledger), indent=JSON_INDENT))
        return 0 if ledger.status in ("COMPLETE", "PAUSED") else 1
    ledger = store.load()
    if args.action == "status":
        print(json.dumps(_status(ledger), indent=JSON_INDENT))
        return 0
    report = build_report(ledger, cfg, _quota_used(cfg))
    (store.dir / "report.json").write_text(report.model_dump_json(indent=JSON_INDENT) + "\n", encoding="utf-8")
    (store.dir / "report.md").write_text(to_markdown(report, ledger), encoding="utf-8")
    print((store.dir / "report.md").relative_to(REPO_ROOT).as_posix())
    return 0
