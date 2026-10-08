"""`lexarena session run ...`: one session, end to end (BUILD_PLAN Step 9; D-079). Spends LLM quota.

    lexarena session run --case-id ID --run-id RUN --mode LEARN|FROZEN|EMPTY --case-seq N
                         [--ablations A,B] [--allow-draft-personas true|false]

Runs in the session process (session credentials only). The last line printed is JSON with `session_id`, which the run
manager reads; a rate limit exits 75 (`lexarena.cli`), so the run pauses and the stage re-runs later (the aborted
session stays recorded as ABORTED; calls already made come from the cache).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from lexarena.app import DEFAULT_ENV_FILE, PROMPTS_ROOT, REPO_ROOT, build_llm_client, configure_llm_logging
from lexarena.cli_judges import PERSONA_ROOT
from lexarena.config import config_sha256, load_config
from lexarena.embedding import FastEmbedder
from lexarena.judges.personas import PersonaRegistry
from lexarena.orchestrator.session import Services, SessionOptions, run_session
from lexarena.prompts import PromptStore
from lexarena.statute_ids import load_statute_aliases
from lexarena.storage.factory import SessionProcess
from lexarena.versioning import git_sha


def _bool(text: str) -> bool:
    if text.lower() not in ("true", "false"):
        raise argparse.ArgumentTypeError("use true or false")
    return text.lower() == "true"


def add_parsers(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    session = sub.add_parser("session").add_subparsers(dest="action", required=True)
    run = session.add_parser("run", help="run one session end to end (spends LLM quota)")
    run.add_argument("--case-id", required=True)
    run.add_argument("--run-id", required=True)
    run.add_argument("--mode", choices=["LEARN", "FROZEN", "EMPTY"], required=True)
    run.add_argument("--case-seq", type=int, required=True)
    run.add_argument("--ablations", default="", help="comma-separated, from runner.ablations")
    run.add_argument("--allow-draft-personas", type=_bool, default=False)


def run(args: argparse.Namespace, config_path: Path) -> int:
    cfg = load_config(config_path)
    configure_llm_logging(cfg)
    ablations = frozenset(a for a in args.ablations.split(",") if a)
    unknown = sorted(ablations - set(cfg.runner.ablations))
    if unknown:
        raise SystemExit(f"unknown ablations {unknown}")
    prompts = PromptStore(PROMPTS_ROOT)
    services = Services(
        llm=build_llm_client(cfg),
        prompts=prompts,
        cfg=cfg,
        embedder=FastEmbedder(cfg.embedding.model, REPO_ROOT / cfg.embedding.cache_dir, cfg.embedding.batch_size),
        aliases=load_statute_aliases(REPO_ROOT / "data" / "statute_aliases.json"),
        personas=PersonaRegistry(PERSONA_ROOT, prompts, cfg.prompts),
        git_sha=git_sha(REPO_ROOT),
        config_sha256=config_sha256(config_path),
        log=lambda line: print(line, file=sys.stderr, flush=True),
    )
    options = SessionOptions(
        run_id=args.run_id,
        mode=args.mode,
        case_seq=args.case_seq,
        ablations=ablations,
        allow_draft_personas=args.allow_draft_personas,
    )
    with SessionProcess.from_env_files([DEFAULT_ENV_FILE]) as proc:
        session = run_session(proc, args.case_id, options, services)
    print(json.dumps({"session_id": session.id, "state": session.state, "winner": session.winner}))
    return 0
