"""Step 7 acceptance: THEMIS-LOCAL layer 1 on arguments built from clerked dev cases (BUILD_PLAN Step 7; D-024).

Arguments:
- HONEST: each side's opening grounds (agent view, pseudonymised) and the real contentions held in ground truth
  (name-free summaries of counsel's submissions); expected: no hard error.
- HONEST_NUMERIC: an honest ground plus a sentence stating a statute's period with the Law DB's own value;
  expected: no hard error.
- MUTATED: the same sentence with the value doubled; expected: ERR_TIMELINE_MISSTATED.
- PRE_THRESHOLD: a ground plus the older minimum default for a case filed before the dated threshold applies;
  expected: no hard error, THRESHOLD_NOT_VERIFIABLE.

Every number in an added sentence is read from the Law DB, never typed here. Sealed reads use the REVIEW role, so
this runs only on cases that have never had a session (D-056). Spends verifier-model quota (Groq); the LLM cache
makes a re-run free.

    .venv/Scripts/python scripts/step7_acceptance.py DEV_0001 DEV_0002 DEV_0003 [--pause 8]
"""

from __future__ import annotations

import argparse
import json
import time
from dataclasses import dataclass, field
from pathlib import Path

from lexarena.app import DEFAULT_ENV_FILE, PROMPTS_ROOT, SEALED_ENV_FILE, build_llm_client, configure_llm_logging
from lexarena.cli import _config_path
from lexarena.config import load_config
from lexarena.prompts import PromptStore
from lexarena.schemas.config import ThemisLocalConfig
from lexarena.schemas.predicate import PredicateEntry
from lexarena.storage.factory import SealedProcess
from lexarena.storage.temporal import AsOf, StatuteView
from lexarena.themis_local.extract import extract_checklists
from lexarena.themis_local.layer1 import CaseFacts, alternative_readings, run_layer1

REPORT = Path("reports/step7_acceptance.md")
RAW = Path("reports/step7_acceptance.json")
# Sentences counsel might write; {n} is filled from the Law DB. The statute is the one the template names.
TIMELINE_TEMPLATES = {
    "adjudication_window_days": [
        "Further, under Section 7(4) of the Code the Adjudicating Authority is required to ascertain the existence "
        "of a default within {n} days of receipt of the application.",
        "The Code allows the Adjudicating Authority {n} days from receipt to decide whether a default has occurred.",
    ],
    "rectification_window_days": [
        "Under the proviso to Section 7(5) of the Code, the applicant must be given {n} days from notice to "
        "rectify any defect in the application.",
        "A defective application under Section 7 may be cured within {n} days of the notice of the defect.",
    ],
}
TIMELINE_STATUTE = "IBC_2016_SEC_7"
THRESHOLD_STATUTE = "IBC_2016_SEC_4"
OLDER_MINIMUM_SENTENCE = (
    "The application was filed when the minimum amount of default under Section 4 of the Code was one lakh rupees, "
    "and the default here is well above that minimum."
)
MUTATION_FACTOR = 2
ALTERNATIVES: dict[str, list[dict[str, StatuteView] | None]] = {}
THEMIS_CFG: list[ThemisLocalConfig] = []


@dataclass
class Argument:
    case_id: str
    kind: str
    text: str
    statutes: list[str]
    expect_hard: list[str]
    expect_warning: str | None = None
    result: dict[str, object] = field(default_factory=dict)


def build_arguments(
    proc: SealedProcess, case_ids: list[str]
) -> tuple[list[Argument], dict[str, dict[str, StatuteView]], dict[str, CaseFacts]]:
    review = proc.review()
    law = proc.clerk().law
    arguments: list[Argument] = []
    views_by_case: dict[str, dict[str, StatuteView]] = {}
    facts_by_case: dict[str, CaseFacts] = {}
    for case_id in case_ids:
        case = review.cases.get(case_id)
        truth = review.ground_truth.get_for_review(case_id)
        av = case.agent_view
        as_of = AsOf.for_case(case)
        invoked = list(av.metadata.statutes_invoked)
        wanted = {*invoked, TIMELINE_STATUTE, THRESHOLD_STATUTE}
        for side in ("PETITIONER", "RESPONDENT"):
            wanted |= {s for sub in getattr(truth.real_submissions, side) for s in sub.statutes_cited}
        views = {sid: v for sid in sorted(wanted) if (v := law.get_statute(sid, as_of)) is not None}
        views_by_case[case_id] = views
        ALTERNATIVES[case_id] = [
            None if alt is None else {sid: v for sid in sorted(wanted) if (v := law.get_statute(sid, alt)) is not None}
            for alt in alternative_readings(as_of, THEMIS_CFG[0])
        ]
        facts_by_case[case_id] = CaseFacts(
            amounts={a.amount_id: a for a in av.record.amounts},
            key_dates={k.label: k.date for k in av.metadata.key_dates},
            date_fact_ids={k.label: k.fact_id for k in av.metadata.key_dates},
        )
        grounds = [g for side in ("PETITIONER", "RESPONDENT") for g in getattr(av.opening_positions, side)]
        for g in grounds:
            arguments.append(Argument(case_id, "HONEST", g.ground, invoked, []))
        for side in ("PETITIONER", "RESPONDENT"):
            for sub in getattr(truth.real_submissions, side):
                arguments.append(
                    Argument(case_id, "HONEST", sub.contention, sorted({*invoked, *sub.statutes_cited}), [])
                )
        base = grounds[0].ground
        timeline_view = views.get(TIMELINE_STATUTE)
        if TIMELINE_STATUTE in invoked and timeline_view is not None:
            for key, templates in TIMELINE_TEMPLATES.items():
                law_value = getattr(timeline_view.record.procedural_timelines, key)
                if law_value is None:
                    continue
                for template in templates:
                    honest = f"{base} {template.format(n=law_value)}"
                    wrong = f"{base} {template.format(n=law_value * MUTATION_FACTOR)}"
                    statutes = sorted({*invoked, TIMELINE_STATUTE})
                    arguments.append(Argument(case_id, "HONEST_NUMERIC", honest, statutes, []))
                    arguments.append(Argument(case_id, "MUTATED", wrong, statutes, ["ERR_TIMELINE_MISSTATED"]))
        threshold_view = views.get(THRESHOLD_STATUTE)
        if threshold_view is not None and not threshold_view.applied and av.metadata.key_dates:
            filing = {k.label: k.date for k in av.metadata.key_dates}.get("FILING")
            if filing is not None:
                arguments.append(
                    Argument(
                        case_id,
                        "PRE_THRESHOLD",
                        f"{base} {OLDER_MINIMUM_SENTENCE}",
                        sorted({*invoked, THRESHOLD_STATUTE}),
                        [],
                        "THRESHOLD_NOT_VERIFIABLE",
                    )
                )
    return arguments, views_by_case, facts_by_case


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("case_ids", nargs="+")
    parser.add_argument("--pause", type=float, default=8.0, help="seconds between model calls (free-tier pacing)")
    args = parser.parse_args()
    cfg = load_config(_config_path(None))
    configure_llm_logging(cfg)
    prompts = PromptStore(PROMPTS_ROOT)
    llm = build_llm_client(cfg)
    THEMIS_CFG.append(cfg.themis_local)
    with SealedProcess.from_env_files([DEFAULT_ENV_FILE, SEALED_ENV_FILE]) as proc:
        arguments, views_by_case, facts_by_case = build_arguments(proc, args.case_ids)
        law = proc.clerk().law
        predicates: dict[str, list[PredicateEntry]] = {}
        for views in views_by_case.values():
            for sid in views:
                predicates.setdefault(sid, law.predicates(sid))
    for i, arg in enumerate(arguments, 1):
        views = {s: v for s, v in views_by_case[arg.case_id].items() if s in arg.statutes}
        started = time.monotonic()
        report = extract_checklists(
            llm, prompts, cfg, arg.text, views, predicates, facts_by_case[arg.case_id].amounts,
            session_id=f"STEP7-{arg.case_id}",
        )  # fmt: skip
        alts = [
            None if a is None else {k: v for k, v in a.items() if k in arg.statutes} for a in ALTERNATIVES[arg.case_id]
        ]
        result = run_layer1(
            report.checklists, views, predicates, facts_by_case[arg.case_id], cfg.themis_local, alternatives=alts
        )
        hard = sorted({e.code for e in result.hard_errors})
        warnings = sorted({w.code for w in [*result.warnings, *report.warnings]})
        arg.result = {
            "hard": hard,
            "hard_detail": [f"{e.code} {e.statute_id}: {e.detail}" for e in result.hard_errors],
            "warnings": warnings,
            "extraction_notes": report.notes,
            "checklists": [c.model_dump(mode="json") for c in report.checklists],
            "seconds": round(time.monotonic() - started, 1),
        }
        ok = hard == arg.expect_hard and (arg.expect_warning is None or arg.expect_warning in warnings)
        arg.result["as_expected"] = ok
        print(
            f"[{i}/{len(arguments)}] {arg.case_id} {arg.kind:15} hard={hard} warn={warnings} {'OK' if ok else 'MISS'}"
        )
        if i < len(arguments):
            time.sleep(args.pause)
    write_report(arguments)
    return 0


def write_report(arguments: list[Argument]) -> None:
    RAW.parent.mkdir(parents=True, exist_ok=True)
    RAW.write_text(json.dumps([a.__dict__ for a in arguments], indent=2, default=str), encoding="utf-8")
    honest = [a for a in arguments if a.kind != "MUTATED"]
    mutated = [a for a in arguments if a.kind == "MUTATED"]
    rejected = [a for a in honest if a.result["hard"]]
    caught = [a for a in mutated if a.result["as_expected"]]
    lines = [
        "# Step 7 acceptance: THEMIS-LOCAL layer 1",
        "",
        f"Arguments: {len(arguments)} ({len(honest)} honest, {len(mutated)} mutated).",
        f"False rejections (honest with any hard error): {len(rejected)} of {len(honest)}"
        f" = {len(rejected) / max(len(honest), 1):.1%}.",
        f"Mutations caught with the expected code: {len(caught)} of {len(mutated)}.",
        "",
        "| # | Case | Kind | Expected hard | Hard | Warnings | As expected |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for i, a in enumerate(arguments, 1):
        lines.append(
            f"| {i} | {a.case_id} | {a.kind} | {', '.join(a.expect_hard) or '-'} | {', '.join(a.result['hard']) or '-'}"  # type: ignore[arg-type]
            f" | {', '.join(a.result['warnings']) or '-'} | {'yes' if a.result['as_expected'] else '**no**'} |"  # type: ignore[arg-type]
        )
    lines += ["", "## Arguments and details", ""]
    for i, a in enumerate(arguments, 1):
        lines += [f"**{i}. {a.case_id} {a.kind}**: {a.text}", ""]
        for d in a.result["hard_detail"]:  # type: ignore[attr-defined]
            lines.append(f"- hard: {d}")
        for n in a.result["extraction_notes"]:  # type: ignore[attr-defined]
            lines.append(f"- note: {n}")
        lines.append("")
    REPORT.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {REPORT}")


if __name__ == "__main__":
    raise SystemExit(main())
