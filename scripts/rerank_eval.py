"""D-055 evidence: does reranking help, which reranker, and how big is a search result?

Known-item retrieval on random precedents (seeded from config): the query is the precedent's own first legal
issue (find_authority) or its own summary (find_similar_cases), with the cut-off set just after its decision so
it is in scope. A good pipeline puts that precedent in the top_k. This is a proxy: the queries are written in the
same style as the stored text, so absolute numbers flatter every setting; the comparison between settings is
what matters. Precedents only (no dev case, none of the 500).

    .venv/Scripts/python scripts/rerank_eval.py [N]
"""

from __future__ import annotations

import json
import random
import re
import sys
import time
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lexarena.app import DEFAULT_ENV_FILE, REPO_ROOT
from lexarena.config import load_config
from lexarena.embedding import FastEmbedder
from lexarena.rerank import FastReranker, Reranker
from lexarena.retrieval.tools import RetrievalTools
from lexarena.schemas.retrieval import CaseScope
from lexarena.statute_ids import load_statute_aliases
from lexarena.storage.factory import SessionProcess
from tests.test_retrieval_tools import agent_view

# bge-reranker-base is left out: 36 s per 150 pairs on this CPU, too slow for a search tool (D-055).
SETTINGS = ["none", "Xenova/ms-marco-MiniLM-L-6-v2"]
SAMPLE_FIELDS = ["precedent_uid", "decision_date", "legal_issues", "summary"]


def first_issue(text: str) -> str:
    parts = [p.strip() for p in re.split(r"(?:^|\s)\d+\.\s", text) if p.strip()]
    return parts[0] if parts else text.strip()


def main(n: int) -> None:
    cfg = load_config(REPO_ROOT / "config" / "config.v1.yaml")
    r = cfg.retrieval
    embedder = FastEmbedder(cfg.embedding.model, REPO_ROOT / cfg.embedding.cache_dir, cfg.embedding.batch_size)
    rerankers: dict[str, Reranker | None] = {"none": None}
    for name in SETTINGS[1:]:
        rerankers[name] = FastReranker(name, REPO_ROOT / cfg.embedding.cache_dir, cfg.embedding.batch_size)
    aliases = load_statute_aliases(REPO_ROOT / "data" / "statute_aliases.json")
    rows: dict[tuple[str, str], dict[str, list[float]]] = {}
    with SessionProcess.from_env_files([DEFAULT_ENV_FILE]) as proc:
        known = proc.orchestrator().law.statute_ids()
        payloads = proc.orchestrator().precedents.all_payloads(SAMPLE_FIELDS)
        rng = random.Random(cfg.seed)
        sample = rng.sample([p for p in payloads if p["legal_issues"].strip() and p["summary"].strip()], n)
        for p in sample:
            scope = CaseScope(
                decided_before=date.fromisoformat(p["decision_date"]) + timedelta(days=1), excluded_precedent_ids=[]
            )
            reader = proc.lawyer("PETITIONER", "rerank-eval", scope).precedents
            for setting, reranker in rerankers.items():
                tools = RetrievalTools(
                    reader=reader,
                    case=agent_view(),
                    embedder=embedder,
                    reranker=reranker,
                    known_statutes=known,
                    aliases=aliases,
                    top_k=r.top_k,
                    candidate_pool=r.candidate_pool,
                    card_text_tokens=r.card_text_tokens,
                    query_instruction=cfg.embedding.query_instruction,
                )
                for kind, run in (
                    ("authority", lambda t=tools, q=p: t.find_authority(first_issue(q["legal_issues"]))),
                    ("similar", lambda t=tools, q=p: t.find_similar_cases(q["summary"])),
                ):
                    t0 = time.perf_counter()
                    result = run()
                    secs = time.perf_counter() - t0
                    uids = [h.precedent_uid for h in result.hits]
                    rank = uids.index(p["precedent_uid"]) + 1 if p["precedent_uid"] in uids else 0
                    m = rows.setdefault((kind, setting), {"hit": [], "rr": [], "secs": [], "tokens": []})
                    m["hit"].append(1.0 if rank else 0.0)
                    m["rr"].append(1 / rank if rank else 0.0)
                    m["secs"].append(secs)
                    m["tokens"].append(embedder.count_tokens(json.dumps(result.model_dump(mode="json"))))
    lines = [
        f"# D-055 reranker evaluation (known-item, n={n}, seed {cfg.seed}, pool {r.candidate_pool}, top_k {r.top_k})",
        "",
        "| search | reranker | recall@k | MRR@k | mean s/query | mean result tokens |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for (kind, setting), m in sorted(rows.items()):
        k = len(m["hit"])
        lines.append(
            f"| {kind} | {setting} | {sum(m['hit']) / k:.2f} | {sum(m['rr']) / k:.2f} | "
            f"{sum(m['secs']) / k:.2f} | {sum(m['tokens']) / k:.0f} |"
        )
    text = "\n".join(lines) + "\n"
    (REPO_ROOT / "reports").mkdir(exist_ok=True)
    (REPO_ROOT / "reports" / "step5b_rerank.md").write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 40)
