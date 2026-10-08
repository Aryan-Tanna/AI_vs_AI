"""`lexarena judges ...` (BUILD_PLAN Step 11; D-048, D-071).

    lexarena judges personas                              approval status of each persona prompt
    lexarena judges draft-personas                        write DRAFT approval files for the current prompt texts
    lexarena judges approve PERSONA --by NAME [--note T]  the owner's approval of the current text (never an agent's)
    lexarena judges reject PERSONA --by NAME --reason T
    lexarena judges trial --case-id DEV_0001 [--allow-draft-personas]   (spends LLM quota)

`trial` runs the real bench on a clerked case with no debate: the judges decide on the pleaded grounds alone (the
agent view's opening positions). It runs in the session process, as the orchestrator will, never touches sealed data,
stores nothing in the database, and writes `reports/bench/<case>_trial.json`. It exists to exercise the bench on real
dev cases before Steps 9 and 10 produce transcripts; it is not a session and its result is not a verdict.
"""

from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path
from typing import Any, cast

from lexarena.app import DEFAULT_ENV_FILE, PROMPTS_ROOT, REPO_ROOT, build_llm_client, configure_llm_logging
from lexarena.config import load_config
from lexarena.embedding import FastEmbedder
from lexarena.judges.personas import PersonaRegistry
from lexarena.judges.run import Bench, BenchInputs, law_for_bench
from lexarena.prompts import PromptStore
from lexarena.retrieval.tools import RetrievalTools, tools_for
from lexarena.schemas.bench import PERSONAS, Persona
from lexarena.schemas.config import AppConfig
from lexarena.schemas.retrieval import CaseScope
from lexarena.statute_ids import load_statute_aliases
from lexarena.storage.factory import SessionProcess
from lexarena.storage.policy import Role
from lexarena.storage.temporal import AsOf

PERSONA_ROOT = REPO_ROOT / "review" / "judge_personas"
BENCH_REPORTS = REPO_ROOT / "reports" / "bench"
JSON_INDENT = 2  # literal-ok: display indentation


def add_parsers(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    judges = sub.add_parser("judges").add_subparsers(dest="action", required=True)
    judges.add_parser("personas", help="approval status of each persona prompt")
    judges.add_parser("draft-personas", help="write DRAFT approval files for the current persona prompt texts")
    approve = judges.add_parser("approve", help="approve a persona prompt's current text (the owner only)")
    approve.add_argument("persona", choices=PERSONAS)
    approve.add_argument("--by", required=True)
    approve.add_argument("--note")
    reject = judges.add_parser("reject", help="reject a persona prompt's current text")
    reject.add_argument("persona", choices=PERSONAS)
    reject.add_argument("--by", required=True)
    reject.add_argument("--reason", required=True)
    trial = judges.add_parser("trial", help="the bench on a clerked case's pleaded grounds (spends LLM quota)")
    trial.add_argument("--case-id", required=True)
    trial.add_argument(
        "--allow-draft-personas",
        action="store_true",
        help="run persona prompts the owner has not approved; every decision is stamped unapproved",
    )


def _registry(cfg: AppConfig) -> PersonaRegistry:
    return PersonaRegistry(PERSONA_ROOT, PromptStore(PROMPTS_ROOT), cfg.prompts)


def _print(value: Any) -> None:
    print(json.dumps(value, indent=JSON_INDENT, ensure_ascii=False, default=str))


def _trial(case_id: str, cfg: AppConfig, allow_draft: bool) -> int:
    configure_llm_logging(cfg)
    session_id = f"{case_id}_TRIAL"
    with SessionProcess.from_env_files([DEFAULT_ENV_FILE]) as proc:
        orch = proc.orchestrator()
        full = orch.cases.get(case_id)
        scope = CaseScope.from_case(full)
        judge = proc.judge(scope)
        case = judge.case.agent_view(case_id)
        law = law_for_bench(case, [], orch.law, AsOf.for_case(full), cfg)
        tools = RetrievalTools(
            reader=judge.precedents,
            case=case,
            embedder=FastEmbedder(cfg.embedding.model, REPO_ROOT / cfg.embedding.cache_dir, cfg.embedding.batch_size),
            reranker=None,
            known_statutes=judge.law.statute_ids(),
            aliases=load_statute_aliases(REPO_ROOT / "data" / "statute_aliases.json"),
            top_k=cfg.retrieval.top_k,
            candidate_pool=cfg.retrieval.candidate_pool,
            card_text_tokens=cfg.retrieval.card_text_tokens,
            query_instruction=cfg.embedding.query_instruction,
        )
        bench = Bench(
            build_llm_client(cfg), PromptStore(PROMPTS_ROOT), cfg, _registry(cfg), allow_unapproved_personas=allow_draft
        )
        inputs = BenchInputs(
            case=case, turns=[], law=law, fetch_precedent=tools_for(Role.JUDGE, tools)["get_precedent"]
        )
        result = bench.decide(inputs, session_id=session_id)
    out = {
        "kind": "PLEADINGS_ONLY_TRIAL",
        "case_id": case_id,
        "note": "No debate: the bench decided on the pleaded grounds alone. Not a session; not a verdict.",
        "statutes_shown": sorted(law.views),
        "notes": result.notes,
        "verdict": result.verdict.to_document(),
        "decisions": [d.to_document() for d in result.decisions],
    }
    BENCH_REPORTS.mkdir(parents=True, exist_ok=True)
    path = BENCH_REPORTS / f"{case_id}_trial.json"
    path.write_text(json.dumps(out, indent=JSON_INDENT, ensure_ascii=False) + "\n", encoding="utf-8")
    v = result.verdict
    _print(
        {
            "case_id": case_id,
            "status": v.status,
            "winner": v.winner,
            "decided_by": v.decided_by,
            "unstable_reason": v.unstable_reason,
            "votes": v.votes,
            "abstaining": v.abstaining_judges,
            "issues": {f.issue_id: f.upholds or f.status for f in v.issue_findings},
            "report": path.relative_to(REPO_ROOT).as_posix(),
        }
    )
    return 0


def run(args: argparse.Namespace, config_path: Path) -> int:
    cfg = load_config(config_path)
    reg = _registry(cfg)
    if args.action == "personas":
        _print(reg.all_status())
        return 0
    if args.action == "draft-personas":
        _print({p: reg.draft(p).status for p in PERSONAS})
        return 0
    persona = cast(Persona, getattr(args, "persona", None))
    if args.action == "approve":
        _print(reg.approve(persona, by=args.by, today=date.today(), note=args.note).to_document())
        return 0
    if args.action == "reject":
        _print(reg.reject(persona, by=args.by, reason=args.reason, today=date.today()).to_document())
        return 0
    return _trial(args.case_id, cfg, args.allow_draft_personas)
