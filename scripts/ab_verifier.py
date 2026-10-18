"""A/B of THEMIS-LOCAL's reasoning effort (owner's option A, 2026-10-19; D-084, D-102, Q-034).

Replays the exact drafts a finished session's verifier saw (every attempt, from its trace) through THEMIS-LOCAL under
one verifier setting, with the same context for every arm (opponent's last turn, own earlier turns, closing), plus
three mechanical mutations of the case's own pleaded ground (invented exhibit content, a record item that does not
exist, an inverted precedent holding) that must be caught. Run once per arm; compare with --compare.

    .venv/Scripts/python scripts/ab_verifier.py --trace runs/live/<session>.jsonl --effort default
    .venv/Scripts/python scripts/ab_verifier.py --trace runs/live/<session>.jsonl --effort low
    .venv/Scripts/python scripts/ab_verifier.py --compare reports/dev_runs/ab_verifier_<case>_default.json \
        reports/dev_runs/ab_verifier_<case>_low.json

Spends verifier quota (Qwen on OpenRouter). Each arm logs under its own session ID, so tokens come from the call log.
"""

from __future__ import annotations

import argparse
import ast
import json
import time
from pathlib import Path
from typing import Any

from lexarena.app import DEFAULT_ENV_FILE, PROMPTS_ROOT, REPO_ROOT, build_llm_client, configure_llm_logging
from lexarena.config import load_config
from lexarena.embedding import FastEmbedder
from lexarena.judges.run import law_for_bench
from lexarena.precedent_text import core_rule
from lexarena.prompts import PromptStore
from lexarena.retrieval.tools import RetrievalTools, tools_for
from lexarena.schemas.agent import DraftClaim, LawyerDraft
from lexarena.schemas.retrieval import CaseScope, PrecedentExcerpt
from lexarena.statute_ids import load_statute_aliases
from lexarena.storage.factory import SessionProcess
from lexarena.storage.policy import Role
from lexarena.storage.temporal import AsOf
from lexarena.themis_local.verify import ThemisLocal, VerifyContext

OUT = REPO_ROOT / "reports" / "dev_runs"


def _value(raw: Any) -> Any:
    return ast.literal_eval(raw) if isinstance(raw, str) else raw


def checks_from_trace(path: Path) -> tuple[str, list[dict[str, Any]]]:
    """Every THEMIS-LOCAL check in order, with the context it was given (published turns before it)."""
    events = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    case_id = events[0]["case_id"]
    published: list[tuple[int, str, str, bool]] = []  # (turn, side, text, is_closing) in publication order
    out: list[dict[str, Any]] = []
    for e in events:
        if e.get("event") == "turn_published":
            p = _value(e["published"]) if not isinstance(e["published"], dict) else e["published"]
            published.append((int(p["turn"]), p["speaker"], p["published_text"], p["turn_type"] == "CLOSING"))
        elif e.get("event") == "themis_check":
            turn, side, closing = int(e["turn"]), e["side"], e.get("turn_type") == "CLOSING"
            # A closing sees the transcript through the last rebuttal and never the other closing (SPEC E6).
            before = [(t, s, x) for t, s, x, c in published if t < turn and not c]
            others = [t for _, s, t in before if s != side]
            out.append(
                {
                    "turn": turn,
                    "side": side,
                    "attempt": int(e.get("attempt", 1)),
                    "closing": closing,
                    "draft": _value(e["draft"]),
                    "recorded_hard_errors": [h.get("code") for h in _value(e.get("hard_errors") or "[]")],
                    "opponent_last": others[-1] if others else None,
                    "own_earlier": [t for _, s, t in before if s == side],
                }
            )
    return case_id, out


def run_arm(trace: Path, effort: str) -> Path:
    cfg = load_config(REPO_ROOT / "config" / "config.v1.yaml")
    if effort != "default":
        cfg = cfg.model_copy(
            update={
                "models": cfg.models.model_copy(
                    update={"verifier": cfg.models.verifier.model_copy(update={"reasoning_effort": effort})}
                )
            }
        )
    configure_llm_logging(cfg)
    case_id, checks = checks_from_trace(trace)
    session_id = f"AB_{effort.upper()}_{case_id}"
    embedder = FastEmbedder(cfg.embedding.model, REPO_ROOT / cfg.embedding.cache_dir, cfg.embedding.batch_size)
    rows: list[dict[str, Any]] = []
    with SessionProcess.from_env_files([DEFAULT_ENV_FILE]) as proc:
        orch = proc.orchestrator()
        full = orch.cases.get(case_id)
        scope = CaseScope.from_case(full)
        lawyer = proc.lawyer("PETITIONER", session_id, scope)
        themis = proc.themis_local("PETITIONER", session_id, scope)
        case = lawyer.case.agent_view(case_id)
        law = law_for_bench(case, [], orch.law, AsOf.for_case(full), cfg)
        common = {
            "case": case,
            "embedder": embedder,
            "reranker": None,
            "known_statutes": lawyer.law.statute_ids(),
            "aliases": load_statute_aliases(REPO_ROOT / "data" / "statute_aliases.json"),
            "top_k": cfg.retrieval.top_k,
            "candidate_pool": cfg.retrieval.candidate_pool,
            "card_text_tokens": cfg.retrieval.card_text_tokens,
            "query_instruction": cfg.embedding.query_instruction,
        }
        search = tools_for(Role.LAWYER, RetrievalTools(reader=lawyer.precedents, **common))
        fetch = tools_for(Role.THEMIS_LOCAL, RetrievalTools(reader=themis.precedents, **common))["get_precedent"]
        llm = build_llm_client(cfg)

        def verify(draft: LawyerDraft, ctx: VerifyContext) -> tuple[list[str], list[str], float]:
            started = time.monotonic()
            checker = ThemisLocal(llm, PromptStore(PROMPTS_ROOT), cfg, embedder)  # fresh per check: no carry-over
            v = checker.check(draft, ctx, session_id=session_id)
            return [p.code for p in v.hard_errors], sorted({w.code for w in v.warnings}), time.monotonic() - started

        for c in checks:
            ctx = VerifyContext(
                case=case,
                law=law,
                fetch_precedent=fetch,
                turn=c["turn"],
                opponent_last=c["opponent_last"],
                own_earlier=c["own_earlier"],
                closing=c["closing"],
            )
            hard, warn, secs = verify(LawyerDraft.model_validate(c["draft"]), ctx)
            rows.append(
                {
                    "kind": "REAL_DRAFT",
                    "turn": c["turn"],
                    "side": c["side"],
                    "attempt": c["attempt"],
                    "recorded_in_session": c["recorded_hard_errors"],
                    "hard_errors": hard,
                    "warnings": warn,
                    "seconds": round(secs, 1),
                }
            )
            print(json.dumps(rows[-1]), flush=True)

        # Mutations of the case's own pleaded ground: each must raise its error.
        ground = case.opening_positions.PETITIONER[0]
        base = LawyerDraft(text=ground.ground, issues_addressed=[ground.issue_id], claims=[], lookups=[])
        mutations: list[tuple[str, LawyerDraft, str]] = []
        if case.record.exhibits:
            ex = case.record.exhibits[0].exhibit_id
            text = (
                f"{base.text} Exhibit {ex} expressly records that the debtor undertook to pay the entire outstanding "
                "amount with interest within thirty days and waived every objection."
            )
            claim = DraftClaim(type="FACT", text=text, record_ids=[ex], statute_id=None, precedent_ids=[])
            mutations.append(
                (
                    "invented exhibit content",
                    base.model_copy(update={"text": text, "claims": [claim]}),
                    "ERR_EXHIBIT_CONTENT_FABRICATED",
                )
            )
        missing = DraftClaim(type="FACT", text=base.text, record_ids=["F999"], statute_id=None, precedent_ids=[])
        mutations.append(
            ("record item that does not exist", base.model_copy(update={"claims": [missing]}), "ERR_FACT_NOT_IN_RECORD")
        )
        hits = search["find_authority"](ground.ground).hits
        if hits:
            hit = hits[0]
            ratio = fetch(hit.precedent_uid, "ratio")
            rule = core_rule(ratio.text) if isinstance(ratio, PrecedentExcerpt) else hit.rule
            inverted = f"It is settled that the opposite holds: it is not the law that {rule[0].lower()}{rule[1:]}"
            claim = DraftClaim(
                type="LAW", text=inverted, record_ids=[], statute_id=None, precedent_ids=[hit.precedent_uid]
            )
            mutations.append(
                (
                    "inverted holding",
                    base.model_copy(update={"text": f"{base.text} {inverted}", "claims": [claim]}),
                    "ERR_PRECEDENT_MISATTRIBUTED",
                )
            )
        for name, draft, expected in mutations:
            ctx = VerifyContext(case=case, law=law, fetch_precedent=fetch, turn=1, opponent_last=None, own_earlier=[])
            hard, warn, secs = verify(draft, ctx)
            rows.append(
                {
                    "kind": "MUTATION",
                    "name": name,
                    "expected": expected,
                    "caught": expected in hard,
                    "hard_errors": hard,
                    "warnings": warn,
                    "seconds": round(secs, 1),
                }
            )
            print(json.dumps(rows[-1]), flush=True)

    tokens = {"input": 0, "output": 0, "calls": 0}
    for line in (REPO_ROOT / cfg.llm.log_path).read_text(encoding="utf-8").splitlines():
        r = json.loads(line)
        if r.get("session_id") == session_id and r.get("role") == "verifier" and r.get("outcome") == "ok":
            tokens["calls"] += 1
            tokens["input"] += r.get("input_tokens") or 0
            tokens["output"] += r.get("output_tokens") or 0
    path = OUT / f"ab_verifier_{case_id}_{effort}.json"
    path.write_text(
        json.dumps({"case_id": case_id, "effort": effort, "tokens": tokens, "rows": rows}, indent=1), encoding="utf-8"
    )
    print(json.dumps({"written": path.as_posix(), "tokens": tokens}))
    return path


def compare(a_path: Path, b_path: Path) -> None:
    a, b = (json.loads(p.read_text(encoding="utf-8")) for p in (a_path, b_path))
    real = [(x, y) for x, y in zip(a["rows"], b["rows"], strict=True) if x["kind"] == "REAL_DRAFT"]
    differ = [(x, y) for x, y in real if sorted(x["hard_errors"]) != sorted(y["hard_errors"])]
    for arm in (a, b):
        rows = arm["rows"]
        drafts = [r for r in rows if r["kind"] == "REAL_DRAFT"]
        muts = [r for r in rows if r["kind"] == "MUTATION"]
        print(
            f"{arm['effort']:>8}: rejected {sum(bool(r['hard_errors']) for r in drafts)}/{len(drafts)} real drafts; "
            f"caught {sum(r['caught'] for r in muts)}/{len(muts)} mutations; "
            f"verifier output {arm['tokens']['output']:,} tokens over {arm['tokens']['calls']} calls; "
            f"time {sum(r['seconds'] for r in rows):,.0f} s"
        )
    print(f"real drafts judged differently: {len(differ)}")
    for x, y in differ:
        where = f"turn {x['turn']} {x['side']} attempt {x['attempt']}"
        print(f"  {where}: {a['effort']} {x['hard_errors']} vs {b['effort']} {y['hard_errors']}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace", type=Path)
    parser.add_argument("--effort", choices=["default", "low", "medium"])
    parser.add_argument("--compare", nargs=2, type=Path)  # literal-ok: two arms
    args = parser.parse_args()
    if args.compare:
        compare(*args.compare)
    else:
        run_arm(args.trace, args.effort)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
