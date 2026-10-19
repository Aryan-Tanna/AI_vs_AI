"""Replay a finished session's bench on its own transcript with today's bench code and config (D-150).

The judges see what they saw in the session: the stored transcript, THEMIS-GLOBAL's stored report, the judge lessons
the session pinned (from its trace) and the same lookup desk, whose own-lesson search is limited to
lessons not learned from this case. First drafts whose prompt is unchanged
come from the response cache; only new checks and revisions call a model. Nothing is written to the session.

    .venv/Scripts/python scripts/replay_bench.py SESSION_ID [--out FILE]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from lexarena.agents.desk import KnowledgeDesk  # noqa: E402
from lexarena.agents.knowledge import CaseLibrary  # noqa: E402
from lexarena.app import (  # noqa: E402
    DEFAULT_ENV_FILE,
    PROMPTS_ROOT,
    REPO_ROOT,
    build_llm_client,
    configure_llm_logging,
)
from lexarena.cli_judges import PERSONA_ROOT  # noqa: E402
from lexarena.config import load_config  # noqa: E402
from lexarena.embedding import FastEmbedder  # noqa: E402
from lexarena.judges.personas import PersonaRegistry  # noqa: E402
from lexarena.judges.run import Bench, BenchInputs, law_for_bench  # noqa: E402
from lexarena.memory.pinning import usable  # noqa: E402
from lexarena.orchestrator.session import lesson_search, statute_resolver  # noqa: E402
from lexarena.prompts import PromptStore  # noqa: E402
from lexarena.retrieval.tools import RetrievalTools  # noqa: E402
from lexarena.schemas.lesson import Lesson  # noqa: E402
from lexarena.schemas.retrieval import CaseScope  # noqa: E402
from lexarena.statute_ids import load_statute_aliases  # noqa: E402
from lexarena.storage.factory import SessionProcess  # noqa: E402
from lexarena.storage.policy import Role  # noqa: E402
from lexarena.storage.temporal import AsOf  # noqa: E402

CONFIG = ROOT / "config" / "config.v1.yaml"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("session_id")
    ap.add_argument("--out", type=Path)
    a = ap.parse_args()
    cfg = load_config(CONFIG)
    configure_llm_logging(cfg)
    prompts = PromptStore(PROMPTS_ROOT)
    llm = build_llm_client(cfg)
    embedder = FastEmbedder(cfg.embedding.model, REPO_ROOT / cfg.embedding.cache_dir, cfg.embedding.batch_size)
    aliases = load_statute_aliases(REPO_ROOT / "data" / "statute_aliases.json")
    with SessionProcess.from_env_files([DEFAULT_ENV_FILE]) as proc:
        orch = proc.orchestrator()
        session = orch.sessions.get(a.session_id)
        full = orch.cases.get(session.case_id)
        scope = CaseScope.from_case(full)
        as_of = AsOf.for_case(full)
        judge_stores = proc.judge(scope)
        case = judge_stores.case.agent_view(session.case_id)
        turns = judge_stores.transcript.turns(a.session_id)
        bench_law = law_for_bench(case, turns, orch.law, as_of, cfg)
        # The judge lessons the session pinned, as its trace recorded them at case opening (D-110).
        opened = next(
            r
            for r in map(json.loads, (REPO_ROOT / cfg.llm.trace_dir / f"{a.session_id}.jsonl").open(encoding="utf-8"))
            if r.get("event") == "case_opened"
        )
        pinned = [Lesson.model_validate(x) for x in opened["judge_lessons"]]
        # The desk's own-lesson search: never a lesson learned from this case itself.
        earlier = [x for x in orch.judge_memory.all() if x.provenance.case_id != session.case_id]
        unkeyed = orch.law.statute_ids_of_types(cfg.memory.unkeyed_jurisdiction_types)
        library = CaseLibrary.for_role(
            Role.JUDGE,
            RetrievalTools(
                reader=judge_stores.precedents,
                case=case,
                embedder=embedder,
                reranker=None,
                known_statutes=set(),
                aliases=aliases,
                top_k=cfg.retrieval.top_k,
                candidate_pool=cfg.retrieval.candidate_pool,
                card_text_tokens=cfg.retrieval.card_text_tokens,
                card_facts_tokens=cfg.retrieval.card_facts_tokens,
                card_cited_max=cfg.retrieval.card_cited_max,
                query_instruction=cfg.embedding.query_instruction,
            ),
        )
        bench = Bench(
            llm, prompts, cfg, PersonaRegistry(PERSONA_ROOT, prompts, cfg.prompts), allow_unapproved_personas=True
        )
        result = bench.decide(
            BenchInputs(
                case=case,
                turns=turns,
                law=bench_law,
                fetch_precedent=library.tools["get_precedent"],
                audit=session.themis_global,
                lessons=pinned,
                hearing_year=full.agent_view.metadata.simulation_date.year,
                desk=KnowledgeDesk(
                    statute=statute_resolver(orch.law, as_of, orch.law.statute_ids(), aliases, bench_law),
                    library=library,
                    lessons=lesson_search(
                        usable(
                            earlier,
                            party_status=None,
                            statutes=set(bench_law.views) - unkeyed,
                            law_versions=session.law_versions,
                            unkeyed=unkeyed,
                        ),
                        exclude={x.lesson_id for x in pinned},
                        embedder=embedder,
                    ),
                    cfg=cfg,
                ),
            ),
            session_id=f"{a.session_id}_BENCH_REPLAY",
        )
    before = session.bench
    out = {
        "session_id": a.session_id,
        "before": {
            "winner": before.winner if before else None,
            "status": before.status if before else None,
            "issues": {f.issue_id: f.upholds for f in before.issue_findings} if before else {},
        },
        "after": {
            "winner": result.verdict.winner,
            "status": result.verdict.status,
            "issues": {f.issue_id: f.upholds for f in result.verdict.issue_findings},
            "votes": result.verdict.votes,
        },
        "opinions": [
            {
                "judge": d.judge,
                "status": d.status,
                "orders": [
                    {
                        "order": o.order,
                        "valid": not hasattr(o, "problems") or not getattr(o, "problems", None),
                        "revised": o.revised,
                        "problems": getattr(o, "problems", []),
                        "issues": [
                            {"issue": x.issue_id, "upholds": x.upholds, "rules": x.governing_rule_ids}
                            for x in getattr(o, "issue_decisions", [])
                        ],
                    }
                    for o in d.opinions
                ],
            }
            for d in result.decisions
        ],
    }
    text = json.dumps(out, indent=1, default=str)
    if a.out:
        a.out.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
