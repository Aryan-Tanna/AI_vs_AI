"""Command line.

  python -m lexarena.cli smoke                      # one tiny call: auth, tools, isolation, window state
  python -m lexarena.cli enqueue debate --split dev --run-id dev1
  python -m lexarena.cli enqueue baseline --cases PC-0001,PC-0002
  python -m lexarena.cli run                        # work until the window is ~full, then exit
  python -m lexarena.cli run --wait                 # keep going across 5-hour windows until the queue is empty
  python -m lexarena.cli status
  python -m lexarena.cli evaluate --run-id dev1 --split dev   # metrics vs sealed ground truth (no model calls)
"""
import argparse
import asyncio
import datetime as dt
import json
import logging
import sys

from lexarena.config import Settings
from lexarena.llm.cache import CachedBackend
from lexarena.orchestrator.handlers import HANDLERS
from lexarena.public_db import UnspoiledStore
from lexarena.session.jobs import JobQueue
from lexarena.session.ledger import UsageLedger
from lexarena.session.runner import SessionReport, Stop, run_session, run_until_done


def _when(ts: float | None) -> str:
    if ts is None or ts == float("inf"):
        return "unknown"
    return dt.datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")


def _backend(settings: Settings, ledger: UsageLedger) -> CachedBackend:
    from lexarena.llm.claude_code import ClaudeCodeBackend   # imported late so `status` works without the SDK
    return CachedBackend(ClaudeCodeBackend(settings, ledger), settings, ledger)


def _print_report(rep: SessionReport) -> None:
    print(f"stopped: {rep.stop.value} | done {rep.done} | failed {rep.failed}"
          + (f" | resume after {_when(rep.resume_at)}" if rep.resume_at else ""))
    for e in rep.errors[:10]:
        print("  error:", e)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="lexarena")
    sub = p.add_subparsers(dest="cmd", required=True)
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
        print(json.dumps({"jobs": queue.counts(), "windows": ledger.summary(),
                          "blocked_until": _when(blocked) if blocked else "not blocked"}, indent=1))
        for key, err in queue.failures():
            print("failed:", key, "-", (err or "")[:200])
        return 0

    if args.cmd == "enqueue":
        store = UnspoiledStore(settings.public_db_dir)
        uids = store.split(args.split) if args.split else [c.strip() for c in args.cases.split(",") if c.strip()]
        added = sum(queue.enqueue(args.kind, f"{args.kind}:{args.run_id}:{uid}", {"case_uid": uid, "run_id": args.run_id})
                    for uid in uids)
        print(f"enqueued {added} new {args.kind} jobs ({len(uids) - added} already queued)")
        return 0

    backend = _backend(settings, ledger)

    if args.cmd == "smoke":
        import time
        queue.enqueue("smoke", f"smoke:{int(time.time())}", {})
        rep = asyncio.run(run_session(queue, backend, ledger, HANDLERS, settings, kinds=["smoke"]))
        _print_report(rep)
        row = queue.db.execute("SELECT result FROM jobs WHERE kind='smoke' AND state='done' ORDER BY id DESC LIMIT 1").fetchone()
        if row:
            res = json.loads(row[0])
            print(json.dumps({k: res[k] for k in ("output", "tool_called", "model")}, indent=1))
        print("windows:", json.dumps(ledger.summary()))
        return 0 if rep.done else 1

    kinds = args.kinds.split(",") if args.kinds else None
    if args.wait:
        def on_pause(rep: SessionReport, wait: float) -> None:
            _print_report(rep)
            print(f"sleeping {wait / 60:.0f} min (until ~{_when(rep.resume_at)}); Ctrl+C is safe — progress is checkpointed")
        reps = asyncio.run(run_until_done(queue, backend, ledger, HANDLERS, settings, kinds, on_pause=on_pause))
        _print_report(reps[-1])
        return 0
    rep = asyncio.run(run_session(queue, backend, ledger, HANDLERS, settings, kinds))
    _print_report(rep)
    return 0 if rep.stop in (Stop.QUEUE_EMPTY, Stop.NEAR_LIMIT, Stop.USAGE_LIMIT, Stop.TIME_CAP) else 1


if __name__ == "__main__":
    sys.exit(main())
