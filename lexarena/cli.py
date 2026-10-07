"""Command line interface supporting both upstream infrastructure and simulation orchestrator.

Upstream commands:
  python -m lexarena.cli --config config/config.v1.yaml config show
  python -m lexarena.cli llm smoke [--role <role>]
  python -m lexarena.cli law validate [--source data/law_db]
  python -m lexarena.cli law load [--source data/law_db]

Simulation commands:
  python -m lexarena.cli smoke
  python -m lexarena.cli enqueue debate --split dev --run-id dev1
  python -m lexarena.cli enqueue baseline --cases PC-0001,PC-0002
  python -m lexarena.cli run
  python -m lexarena.cli run --wait
  python -m lexarena.cli status
  python -m lexarena.cli evaluate --run-id dev1 --split dev
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
import logging
import sys
from collections.abc import Sequence
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from lexarena.app import (
    DEFAULT_ENV_FILE,
    PROMPTS_ROOT,
    REPO_ROOT,
    SEALED_ENV_FILE,
    build_llm_client,
    configure_llm_logging,
)
from lexarena.config import config_sha256, load_config
from lexarena.llm.errors import LLMError
from lexarena.prompts import PromptStore
from lexarena.settings import Settings as AppSettings


class SmokeAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    answer: int
    unit: str


def _config_path(arg: str | None) -> Path:
    return Path(arg) if arg else AppSettings().config_path


def _config_show(path: Path) -> int:
    cfg = load_config(path)
    out = {
        "version": cfg.version,
        "config_path": str(path),
        "config_sha256": config_sha256(path),
        "providers": sorted(cfg.providers),
        "models": {role: m.model_dump() for role, m in cfg.models.by_role().items()},
        "seed": cfg.seed,
    }
    print(json.dumps(out, indent=2))  # literal-ok: display indentation
    return 0


def _llm_smoke(path: Path, roles: list[str] | None) -> int:
    cfg = load_config(path)
    configure_llm_logging(cfg)
    client = build_llm_client(cfg, use_cache=False)
    prompt = PromptStore(PROMPTS_ROOT).render(cfg.prompts.smoke.id, cfg.prompts.smoke.version)
    failures = 0
    for role in roles or list(cfg.models.by_role()):
        model = cfg.models.by_role()[role]
        try:
            result = client.complete_json(role=role, user=prompt, schema=SmokeAnswer, session_id=f"smoke-{role}")
            print(
                json.dumps(
                    {
                        "role": role,
                        "provider": model.provider,
                        "model": model.name,
                        "value": result.value.model_dump(),
                        "attempts": result.attempts,
                        "input_tokens": result.input_tokens,
                        "output_tokens": result.output_tokens,
                    }
                )
            )
        except LLMError as exc:
            failures += 1
            print(json.dumps({"role": role, "model": model.name, "error": type(exc).__name__, "detail": str(exc)}))
    return 1 if failures else 0


def _law(action: str, source: Path) -> int:
    from lexarena.ingest.law_db import load_law_db, read_law_sources, validate_law_db
    from lexarena.storage.factory import SealedProcess

    report = validate_law_db(*read_law_sources(source), source=str(source))
    out: dict[str, object] = {"report": report.model_dump(mode="json")}
    if action == "load":
        if not report.loadable:
            print(json.dumps(out, indent=2, ensure_ascii=False))  # literal-ok: display indentation
            return 1
        with SealedProcess.from_env_files([DEFAULT_ENV_FILE, SEALED_ENV_FILE]) as proc:
            result = load_law_db(proc.ingest().law, report)
        out["loaded"] = vars(result)
    print(json.dumps(out, indent=2, ensure_ascii=False))  # literal-ok: display indentation
    return 0 if report.loadable else 1


def _when(ts: float | None) -> str:
    if ts is None or ts == float("inf"):
        return "unknown"
    return dt.datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")


def _backend(settings: Any, ledger: Any) -> Any:
    from lexarena.llm.cache import CachedBackend
    from lexarena.llm.claude_code import ClaudeCodeBackend
    return CachedBackend(ClaudeCodeBackend(settings, ledger), settings, ledger)


def _print_report(rep: Any) -> None:
    print(
        f"stopped: {rep.stop.value} | done {rep.done} | failed {rep.failed}"
        + (f" | resume after {_when(rep.resume_at)}" if rep.resume_at else "")
    )
    for e in rep.errors[:10]:  # literal-ok: error summary limit
        print("  error:", e)


def main(argv: Sequence[str] | None = None) -> int:
    from lexarena.config import Settings
    from lexarena.orchestrator.handlers import HANDLERS
    from lexarena.public_db import UnspoiledStore
    from lexarena.session.jobs import JobQueue
    from lexarena.session.ledger import UsageLedger
    from lexarena.session.runner import SessionReport, Stop, run_session, run_until_done

    p = argparse.ArgumentParser(prog="lexarena")
    p.add_argument("--config", help="config file (default: LEXARENA_CONFIG_PATH)")
    sub = p.add_subparsers(dest="cmd", required=True)

    # Upstream config group
    config_cmd = sub.add_parser("config")
    config_sub = config_cmd.add_subparsers(dest="action", required=True)
    config_sub.add_parser("show", help="print the resolved config summary and its hash")

    # Upstream llm group
    llm_cmd = sub.add_parser("llm")
    llm_sub = llm_cmd.add_subparsers(dest="action", required=True)
    smoke_llm = llm_sub.add_parser("smoke", help="one real schema-validated call per role (spends quota)")
    smoke_llm.add_argument("--role", action="append", help="limit to this role (repeatable)")

    # Upstream law group
    law_cmd = sub.add_parser("law")
    law_sub = law_cmd.add_subparsers(dest="action", required=True)
    for act, text in (("validate", "validation report only"), ("load", "validate, then load into MongoDB")):
        cmd = law_sub.add_parser(act, help=text)
        cmd.add_argument("--source", type=Path, default=REPO_ROOT / "data" / "law_db", help="folder of Law DB files")

    # Simulation subcommands
    sub.add_parser("smoke")
    e = sub.add_parser("enqueue")
    e.add_argument("kind", choices=sorted(set(HANDLERS) - {"smoke"}))
    g = e.add_mutually_exclusive_group(required=True)
    g.add_argument("--split")
    g.add_argument("--cases", help="comma-separated case_uids")
    e.add_argument("--run-id", default="dev")

    r = sub.add_parser("run")
    r.add_argument("--wait", action="store_true", help="sleep through window resets until the queue is empty")
    r.add_argument("--kinds", help="comma-separated job kinds to run")

    sub.add_parser("status")
    ev = sub.add_parser("evaluate")
    ev.add_argument("--run-id", required=True)
    ev.add_argument("--split", default="dev")

    args = p.parse_args(argv)

    # Route upstream commands
    if args.cmd == "config":
        path = _config_path(args.config)
        return _config_show(path)
    if args.cmd == "llm":
        path = _config_path(args.config)
        return _llm_smoke(path, args.role)
    if args.cmd == "law":
        return _law(args.action, args.source)

    # Route simulation commands
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    settings = Settings()
    ledger = UsageLedger(settings.ledger_path)
    queue = JobQueue(settings.jobs_db)

    if args.cmd == "evaluate":
        from lexarena.eval.evaluate import evaluate

        res = evaluate(settings, args.run_id, args.split)
        print((settings.runs_dir / args.run_id / "metrics.md").read_text(encoding="utf-8"))
        return 0 if res["cases_scored"] else 1

    if args.cmd == "status":
        blocked = ledger.blocked_until()
        print(
            json.dumps(
                {
                    "jobs": queue.counts(),
                    "windows": ledger.summary(),
                    "blocked_until": _when(blocked) if blocked else "not blocked",
                },
                indent=1,
            )
        )
        for key, err in queue.failures():
            print("failed:", key, "-", (err or "")[:200])  # literal-ok: truncate display
        return 0

    if args.cmd == "enqueue":
        store = UnspoiledStore(settings.public_db_dir)
        uids = store.split(args.split) if args.split else [c.strip() for c in args.cases.split(",") if c.strip()]
        added = sum(
            queue.enqueue(args.kind, f"{args.kind}:{args.run_id}:{uid}", {"case_uid": uid, "run_id": args.run_id})
            for uid in uids
        )
        print(f"enqueued {added} new {args.kind} jobs ({len(uids) - added} already queued)")
        return 0

    backend = _backend(settings, ledger)

    if args.cmd == "smoke":
        import time

        queue.enqueue("smoke", f"smoke:{int(time.time())}", {})
        rep = asyncio.run(run_session(queue, backend, ledger, HANDLERS, settings, kinds=["smoke"]))
        _print_report(rep)
        row = queue.db.execute(
            "SELECT result FROM jobs WHERE kind='smoke' AND state='done' ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if row:
            res = json.loads(row[0])
            print(json.dumps({k: res[k] for k in ("output", "tool_called", "model")}, indent=1))
        print("windows:", json.dumps(ledger.summary()))
        return 0 if rep.done else 1

    kinds = args.kinds.split(",") if args.kinds else None
    if args.wait:

        def on_pause(rep: SessionReport, wait: float) -> None:
            _print_report(rep)
            print(
                f"sleeping {wait / 60:.0f} min (until ~{_when(rep.resume_at)}); Ctrl+C is safe — progress is checkpointed"  # literal-ok: seconds to minutes
            )

        reps = asyncio.run(run_until_done(queue, backend, ledger, HANDLERS, settings, kinds, on_pause=on_pause))
        _print_report(reps[-1])
        return 0
    rep = asyncio.run(run_session(queue, backend, ledger, HANDLERS, settings, kinds))
    _print_report(rep)
    return 0 if rep.stop in (Stop.QUEUE_EMPTY, Stop.NEAR_LIMIT, Stop.USAGE_LIMIT, Stop.TIME_CAP) else 1


if __name__ == "__main__":
    sys.exit(main())
