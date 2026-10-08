"""`lexarena evaluate ...` and `lexarena baseline ...` (BUILD_PLAN Step 12; D-072).

    lexarena evaluate session SESSION_ID [--baseline FILE] [--out FILE]   sealed process, EVALUATOR role
    lexarena evaluate report --outcomes FILE [FILE ...] [--out FILE]      outcomes in the order the cases ran
    lexarena baseline single --case-id ID --out FILE                      session process; spends one LLM call
    lexarena reflect session SESSION_ID --run-id RUN                      sealed, REFLECTION role; LEARN runs only

`evaluate session` unseals ground truth through the repository (refused before the verdict), records the evaluation
(VERDICT_RECORDED -> EVALUATED) and writes the case outcome. It is a separate process from any session by design: the
run manager starts it as a subprocess, so sealed credentials never share memory with an agent (D-034).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from lexarena.app import (
    DEFAULT_ENV_FILE,
    PROMPTS_ROOT,
    REPO_ROOT,
    SEALED_ENV_FILE,
    build_llm_client,
    configure_llm_logging,
)
from lexarena.baselines.single_llm import predict
from lexarena.config import load_config
from lexarena.embedding import FastEmbedder
from lexarena.evaluator.evaluate import evaluate_session
from lexarena.evaluator.report import evaluation_report
from lexarena.judges.run import law_for_bench
from lexarena.prompts import PromptStore
from lexarena.reflection.reflect import Reflection
from lexarena.schemas.base import SIDES
from lexarena.schemas.evaluation import BaselinePrediction, CaseOutcome
from lexarena.storage.factory import SealedProcess, SessionProcess
from lexarena.storage.temporal import AsOf

JSON_INDENT = 2  # literal-ok: display indentation


def add_parsers(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    ev = sub.add_parser("evaluate").add_subparsers(dest="action", required=True)
    session = ev.add_parser("session", help="compare one session's bench verdict with the sealed judgment")
    session.add_argument("session_id")
    session.add_argument("--baseline", type=Path, help="the single-LLM prediction for the case (JSON)")
    session.add_argument("--out", type=Path, help="write the case outcome here (JSON)")
    report = ev.add_parser("report", help="metrics over evaluated case outcomes")
    report.add_argument("--outcomes", type=Path, nargs="+", required=True, help="outcome files, in the order run")
    report.add_argument("--out", type=Path)
    refl = sub.add_parser("reflect").add_subparsers(dest="action", required=True)
    one = refl.add_parser("session", help="write lessons from an evaluated session (spends reflection quota)")
    one.add_argument("session_id")
    one.add_argument("--run-id", required=True, help="the run the lessons are created in")
    base = sub.add_parser("baseline").add_subparsers(dest="action", required=True)
    single = base.add_parser("single", help="the single-LLM baseline on one case file (spends one call)")
    single.add_argument("--case-id", required=True)
    single.add_argument("--out", type=Path, required=True)


def _write(path: Path | None, value: dict[str, Any]) -> None:
    text = json.dumps(value, indent=JSON_INDENT, ensure_ascii=False) + "\n"
    if path is None:
        print(text, end="")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _session(session_id: str, baseline: Path | None, out: Path | None) -> int:
    single = (
        BaselinePrediction.model_validate_json(baseline.read_text(encoding="utf-8"))
        if baseline is not None and baseline.is_file()
        else None
    )
    with SealedProcess.from_env_files([DEFAULT_ENV_FILE, SEALED_ENV_FILE]) as proc:
        result = evaluate_session(proc.evaluator(), session_id, single)
    _write(out, result.outcome.to_document())
    evaluation = result.session.evaluation
    print(
        json.dumps(
            {
                "session_id": session_id,
                "state": result.session.state,
                "winner_matches_real": evaluation.winner_matches_real if evaluation else None,
                "issue_alignment": evaluation.issue_alignment if evaluation else None,
            }
        )
    )
    return 0


def _report(paths: list[Path], out: Path | None, config_path: Path) -> int:
    cfg = load_config(config_path)
    outcomes = [CaseOutcome.model_validate_json(p.read_text(encoding="utf-8")) for p in paths]
    _write(out, evaluation_report(outcomes, cfg.evaluation, cfg.seed).to_document())
    return 0


def _baseline(case_id: str, out: Path, config_path: Path) -> int:
    cfg = load_config(config_path)
    configure_llm_logging(cfg)
    with SessionProcess.from_env_files([DEFAULT_ENV_FILE]) as proc:
        orch = proc.orchestrator()
        full = orch.cases.get(case_id)
        case = orch.cases.agent_view(case_id)
        law = law_for_bench(case, [], orch.law, AsOf.for_case(full), cfg)
        prediction = predict(
            build_llm_client(cfg), PromptStore(PROMPTS_ROOT), cfg, case, law.views, session_id=f"{case_id}_BASELINE"
        )
    _write(out, prediction.to_document())
    return 0


def _reflect(session_id: str, run_id: str, config_path: Path) -> int:
    cfg = load_config(config_path)
    configure_llm_logging(cfg)
    embedder = FastEmbedder(cfg.embedding.model, REPO_ROOT / cfg.embedding.cache_dir, cfg.embedding.batch_size)
    engine = Reflection(build_llm_client(cfg), PromptStore(PROMPTS_ROOT), cfg, embedder)
    with SealedProcess.from_env_files([DEFAULT_ENV_FILE, SEALED_ENV_FILE]) as proc:
        private = {side: proc.reflection(side).private_turns for side in SIDES}
        result = engine.reflect(proc.reflection(), private, session_id, run_id=run_id)
    print(
        json.dumps(
            {
                "session_id": session_id,
                "state": result.session.state,
                "written": result.written,
                "updated": result.updated,
                "rejected": result.rejected,
                "placements": result.placements,
            }
        )
    )
    return 0


def run(args: argparse.Namespace, config_path: Path) -> int:
    if args.group == "reflect":
        return _reflect(args.session_id, args.run_id, config_path)
    if args.group == "baseline":
        return _baseline(args.case_id, args.out, config_path)
    if args.action == "session":
        return _session(args.session_id, args.baseline, args.out)
    return _report(args.outcomes, args.out, config_path)
