"""BUILD_PLAN Step 8 acceptance on a clerked dev case (D-075): a fabricated exhibit claim and an inverted holding are
caught, unverifiable citations warn rather than reject, and the first-attempt pass rate on honest arguments is
reported. Honest arguments are the case's own pleaded grounds (agent-visible, from the judgment); the others are
mechanical mutations of them. Spends verifier quota (about 3 calls per argument; cached on re-runs).

    .venv/Scripts/python scripts/step8_acceptance.py [--case-id DEV_0001]
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass

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

AUTHORITY_QUERY = "a written acknowledgment of liability before limitation expires starts a fresh period of limitation"


@dataclass
class Argument:
    name: str
    kind: str  # HONEST or MUTATED
    draft: LawyerDraft
    expected: str | None  # the hard error a mutation must raise; None for honest arguments


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case-id", default="DEV_0001")
    case_id = parser.parse_args().case_id
    cfg = load_config(REPO_ROOT / "config" / "config.v1.yaml")
    configure_llm_logging(cfg)
    embedder = FastEmbedder(cfg.embedding.model, REPO_ROOT / cfg.embedding.cache_dir, cfg.embedding.batch_size)
    with SessionProcess.from_env_files([DEFAULT_ENV_FILE]) as proc:
        orch = proc.orchestrator()
        full = orch.cases.get(case_id)
        scope = CaseScope.from_case(full)
        lawyer = proc.lawyer("PETITIONER", f"{case_id}_STEP8", scope)
        themis = proc.themis_local("PETITIONER", f"{case_id}_STEP8", scope)
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
        hit = search["find_authority"](AUTHORITY_QUERY).hits[0]
        full_ratio = fetch(hit.precedent_uid, "ratio")
        rule = core_rule(full_ratio.text) if isinstance(full_ratio, PrecedentExcerpt) else hit.rule
        exhibit = case.record.exhibits[0] if case.record.exhibits else None
        arguments: list[Argument] = []
        for side in ("PETITIONER", "RESPONDENT"):
            for n, g in enumerate(case.opening_positions.for_side(side), 1):  # type: ignore[arg-type]
                arguments.append(
                    Argument(
                        f"{side} ground {n}",
                        "HONEST",
                        LawyerDraft(text=g.ground, issues_addressed=[g.issue_id], claims=[]),
                        None,
                    )
                )
        base = arguments[0].draft
        if exhibit is not None:
            fabricated = (
                f"{base.text} Exhibit {exhibit.exhibit_id} expressly records that the debtor undertook to pay the "
                "entire outstanding amount with interest within thirty days and waived every objection to limitation."
            )
            arguments.append(
                Argument(
                    "fabricated exhibit content",
                    "MUTATED",
                    LawyerDraft(
                        text=fabricated,
                        issues_addressed=base.issues_addressed,
                        claims=[
                            DraftClaim(
                                type="FACT",
                                text=fabricated,
                                record_ids=[exhibit.exhibit_id],
                                statute_id=None,
                                precedent_ids=[],
                            )
                        ],
                    ),
                    "ERR_EXHIBIT_CONTENT_FABRICATED",
                )
            )
        arguments.append(
            Argument(
                "record item that does not exist",
                "MUTATED",
                LawyerDraft(
                    text=base.text,
                    issues_addressed=base.issues_addressed,
                    claims=[
                        DraftClaim(type="FACT", text=base.text, record_ids=["F999"], statute_id=None, precedent_ids=[])
                    ],
                ),
                "ERR_FACT_NOT_IN_RECORD",
            )
        )
        honest_cite = f"{base.text} As held, {rule}"
        arguments.append(
            Argument(
                "honest citation (the precedent's own rule)",
                "HONEST",
                LawyerDraft(
                    text=honest_cite,
                    issues_addressed=base.issues_addressed,
                    claims=[
                        DraftClaim(
                            type="LAW", text=rule, record_ids=[], statute_id=None, precedent_ids=[hit.precedent_uid]
                        )
                    ],
                ),
                None,
            )
        )
        inverted = f"It is settled that the opposite holds: it is not the law that {rule[0].lower()}{rule[1:]}"
        arguments.append(
            Argument(
                "inverted holding",
                "MUTATED",
                LawyerDraft(
                    text=f"{base.text} {inverted}",
                    issues_addressed=base.issues_addressed,
                    claims=[
                        DraftClaim(
                            type="LAW", text=inverted, record_ids=[], statute_id=None, precedent_ids=[hit.precedent_uid]
                        )
                    ],
                ),
                "ERR_PRECEDENT_MISATTRIBUTED",
            )
        )
        arguments.append(
            Argument(
                "unverifiable citation",
                "HONEST",
                LawyerDraft(
                    text=base.text,
                    issues_addressed=base.issues_addressed,
                    claims=[
                        DraftClaim(
                            type="LAW",
                            text=base.text,
                            record_ids=[],
                            statute_id=None,
                            precedent_ids=["NOT_A_PRECEDENT#000000000000"],
                        )
                    ],
                ),
                None,
            )
        )
        themis_local = ThemisLocal(build_llm_client(cfg), PromptStore(PROMPTS_ROOT), cfg, embedder)
        rows = []
        for n, arg in enumerate(arguments, 1):
            ctx = VerifyContext(case=case, law=law, fetch_precedent=fetch, turn=n, opponent_last=None, own_earlier=[])
            v = themis_local.check(arg.draft, ctx, session_id=f"{case_id}_STEP8")
            codes = [p.code for p in v.hard_errors]
            ok = (not codes) if arg.expected is None else (arg.expected in codes)
            rows.append(
                {
                    "argument": arg.name,
                    "kind": arg.kind,
                    "expected": arg.expected,
                    "hard_errors": codes,
                    "warnings": sorted({w.code for w in v.warnings}),
                    "citation": [a.model_dump() for a in v.assessments],
                    "as_expected": ok,
                }
            )
    honest = [r for r in rows if r["kind"] == "HONEST"]
    mutated = [r for r in rows if r["kind"] == "MUTATED"]
    summary = {
        "case_id": case_id,
        "precedent_used": hit.precedent_uid,
        "honest_first_attempt_pass_rate": sum(not r["hard_errors"] for r in honest) / len(honest),
        "honest": len(honest),
        "mutations_caught": f"{sum(r['as_expected'] for r in mutated)}/{len(mutated)}",
    }
    lines = ["# Step 8 acceptance: THEMIS-LOCAL layer 2", "", "```json", json.dumps(summary, indent=2), "```", ""]
    lines += ["| argument | kind | expected | hard errors | warnings | as expected |", "| --- " * 6 + "|"]
    for r in rows:
        lines.append(
            f"| {r['argument']} | {r['kind']} | {r['expected'] or '-'} | {', '.join(r['hard_errors']) or '-'} | "
            f"{', '.join(r['warnings']) or '-'} | {'yes' if r['as_expected'] else '**no**'} |"
        )
    (REPO_ROOT / "reports" / "step8_acceptance.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))
    for r in rows:
        print(r["argument"], "|", r["hard_errors"], "|", r["warnings"], "|", r["as_expected"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
