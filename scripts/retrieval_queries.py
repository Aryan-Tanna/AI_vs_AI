"""BUILD_PLAN Step 5 acceptance: hand-written queries through the real retrieval tools, for the owner's review.

Runs as a LAWYER session bundle (read-only Qdrant key, scope bound at construction), exactly the path an agent
will use. The queries are generic IBC questions written for this check, not taken from any dev case. Writes
reports/step5_queries.md and prints a summary.

    .venv/Scripts/python scripts/retrieval_queries.py
"""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lexarena.app import DEFAULT_ENV_FILE, REPO_ROOT
from lexarena.config import load_config
from lexarena.embedding import FastEmbedder
from lexarena.rerank import FastReranker
from lexarena.retrieval.tools import RetrievalTools
from lexarena.schemas.retrieval import CaseScope, SearchResult
from lexarena.statute_ids import load_statute_aliases
from lexarena.storage.factory import SessionProcess
from tests.test_retrieval_tools import agent_view

QUERIES: list[tuple[str, str, str, list[str] | None]] = [
    (
        "authority",
        "2022-01-01",
        "An application under Section 7 is barred by limitation if filed more than three years after the date of "
        "default, unless the period is extended by a written acknowledgment of the debt.",
        None,
    ),
    (
        "authority",
        "2020-01-01",
        "An operational creditor's application must be rejected where the corporate debtor raised a genuine dispute "
        "about the debt before the demand notice was received.",
        None,
    ),
    (
        "similar",
        "2021-06-01",
        "Homebuyers paid instalments to a real estate developer for flats; possession was not delivered by the "
        "promised date and the allottees applied to start insolvency against the developer.",
        None,
    ),
    (
        "authority",
        "2021-01-01",
        "The commercial wisdom of the Committee of Creditors in approving a resolution plan is not open to review by "
        "the Adjudicating Authority beyond the requirements of the Code for the plan.",
        ["IBC_2016_SEC_30", "IBC_2016_SEC_31"],
    ),
    (
        "similar",
        "2023-01-01",
        "The corporate debtor defaulted on a term loan; the bank classified the account as a non-performing asset; "
        "the company's later balance sheets recorded the debt; the bank filed for insolvency years after the NPA.",
        None,
    ),
]


def main() -> None:
    cfg = load_config(REPO_ROOT / "config" / "config.v1.yaml")
    embedder = FastEmbedder(cfg.embedding.model, REPO_ROOT / cfg.embedding.cache_dir, cfg.embedding.batch_size)
    rr = cfg.retrieval.reranker
    reranker = (
        FastReranker(rr.model, REPO_ROOT / cfg.embedding.cache_dir, cfg.embedding.batch_size) if rr.enabled else None
    )
    aliases = load_statute_aliases(REPO_ROOT / "data" / "statute_aliases.json")
    out = ["# Step 5: hand-written retrieval queries", ""]
    with SessionProcess.from_env_files([DEFAULT_ENV_FILE]) as proc:
        for n, (kind, cutoff, text, statutes) in enumerate(QUERIES, 1):
            scope = CaseScope(decided_before=date.fromisoformat(cutoff), excluded_precedent_ids=[])
            stores = proc.lawyer("PETITIONER", f"step5-q{n}", scope)
            tools = RetrievalTools(
                reader=stores.precedents,
                case=agent_view(),
                embedder=embedder,
                known_statutes=stores.law.statute_ids(),
                aliases=aliases,
                reranker=reranker,
                top_k=cfg.retrieval.top_k,
                candidate_pool=cfg.retrieval.candidate_pool,
                card_text_tokens=cfg.retrieval.card_text_tokens,
                query_instruction=cfg.embedding.query_instruction,
            )
            tool_name = "find_authority" if kind == "authority" else "find_similar_cases"
            result: SearchResult = (
                tools.find_authority(text, statutes)
                if kind == "authority"
                else tools.find_similar_cases(text, statutes)
            )
            out += [
                f"## Q{n}: {tool_name}, decided before {cutoff}",
                "",
                f"> {text}",
                "",
                f"Statute filter: {result.statute_filter or 'none'}; ignored: {result.ignored_statutes or 'none'}",
                "",
                "| # | score | decided | precedent_id | title | statutes (first 4) |",
                "| --- | --- | --- | --- | --- | --- |",
            ]
            for i, h in enumerate(result.hits, 1):
                out.append(
                    f"| {i} | {h.score:.3f} | {h.decision_date} | {h.precedent_id} | {h.case_title[:70]} | "
                    f"{', '.join(h.statutes[:4])} |"
                )
            out.append("")
            for i, h in enumerate(result.hits, 1):
                out.append(f"{i}. rule: {h.rule}")
                out.append(f"   matched: {h.matched}")
            out.append("")
            late = [h.decision_date for h in result.hits if h.decision_date >= cutoff]
            tokens = embedder.count_tokens(json.dumps(result.model_dump(mode="json")))
            out.append(f"Result size: {tokens} tokens (bge tokenizer)")
            out.append("")
            print(
                f"Q{n} {kind:9} before {cutoff}: {len(result.hits)} hits, scores "
                f"{[round(h.score or 0, 3) for h in result.hits]}, dates {[h.decision_date for h in result.hits]}, "
                f"late={late}, tokens={tokens}"
            )
    report = REPO_ROOT / "reports" / "step5_queries.md"
    report.parent.mkdir(exist_ok=True)
    report.write_text("\n".join(out) + "\n", encoding="utf-8")
    print(f"wrote {report.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
