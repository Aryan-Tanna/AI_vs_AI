"""`lexarena clerk ...` (BUILD_PLAN Step 6, D-056).

    lexarena clerk run --file "data/dev/<pdf>" --case-id DEV_0001   (spends LLM quota; stores only a clean case)
    lexarena clerk show DEV_0001          (REVIEW role: the sealed record, only before the case's first session)
    lexarena clerk approve DEV_0001 --by NAME   (marks the case human-reviewed; the clerk role writes it)

Runs in the sealed process: the clerk writes the case, the sealed ground truth and the judgment text. A dev case's
forum and decision date come from `data/dev/dev_cases.json`; only DEV_CASE and SHORT_ORDER files may be clerked.
"""

from __future__ import annotations

import argparse
import json
from datetime import date
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
from lexarena.clerk.pipeline import clerk_judgment
from lexarena.clerk.review import render_review
from lexarena.clerk.text import BLOCK_MARK
from lexarena.config import load_config
from lexarena.drafting.pdf import pdf_pages_blocks
from lexarena.prompts import PromptStore
from lexarena.statute_ids import load_statute_aliases
from lexarena.storage.factory import SealedProcess

DEV_ROOT = REPO_ROOT / "data" / "dev"
REVIEW_DIR = REPO_ROOT / "reports" / "review"
CLERKABLE = ("DEV_CASE", "SHORT_ORDER")
OVERLAP_FIELDS = ["precedent_id", "precedent_uid", "case_title", "appeal_number", "decision_date"]


def add_parsers(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    clerk = sub.add_parser("clerk").add_subparsers(dest="action", required=True)
    run = clerk.add_parser("run", help="clerk one dev judgment (spends LLM quota)")
    run.add_argument("--file", type=Path, required=True, help="the PDF, under data/dev")
    run.add_argument("--case-id", required=True, help="opaque case ID, e.g. DEV_0001 (never from names or numbers)")
    show = clerk.add_parser("show", help="the sealed record, through the REVIEW role, before the first session")
    show.add_argument("case_id")
    approve = clerk.add_parser("approve", help="mark a clerked case as reviewed by you")
    approve.add_argument("case_id")
    approve.add_argument("--by", required=True)


def _manifest_entry(pdf: Path) -> dict[str, Any]:
    rel = pdf.resolve().relative_to(DEV_ROOT.resolve()).as_posix()
    files: list[dict[str, Any]] = json.loads((DEV_ROOT / "dev_cases.json").read_text(encoding="utf-8"))["files"]
    entry = next((f for f in files if f["file"] == rel), None)
    if entry is None:
        raise SystemExit(f"{rel} is not listed in data/dev/dev_cases.json")
    if entry["status"] not in CLERKABLE or entry.get("decided") is None:
        raise SystemExit(f"{rel} is {entry['status']}: not a case to clerk")
    return entry


def _run(pdf: Path, case_id: str, config_path: Path) -> int:
    cfg = load_config(config_path)
    configure_llm_logging(cfg)
    entry = _manifest_entry(pdf)
    data = pdf.read_bytes()
    pages = pdf_pages_blocks(data, BLOCK_MARK)
    with SealedProcess.from_env_files([DEFAULT_ENV_FILE, SEALED_ENV_FILE]) as proc:
        stores = proc.clerk()
        outcome = clerk_judgment(
            pages,
            source_file=entry["file"],
            source_bytes=data,
            case_id=case_id,
            forum=entry["forum"],
            decided=date.fromisoformat(entry["decided"]),
            split_name="DEV",
            llm=build_llm_client(cfg),
            prompts=PromptStore(PROMPTS_ROOT),
            cfg=cfg,
            known_statutes=stores.law.statute_ids(),
            aliases=load_statute_aliases(REPO_ROOT / "data" / "statute_aliases.json"),
            precedent_payloads=stores.precedents.all_payloads(OVERLAP_FIELDS),
        )
        REVIEW_DIR.mkdir(parents=True, exist_ok=True)
        review = REVIEW_DIR / f"{case_id}.md"
        review.write_text(render_review(outcome, entry["file"]), encoding="utf-8")
        stored = not outcome.problems and outcome.case is not None and outcome.truth is not None
        if stored:
            assert outcome.case is not None and outcome.truth is not None
            stores.cases.put(outcome.case)
            stores.ground_truth.put(outcome.truth)
            stores.judgment_texts.put(outcome.judgment)
    print(
        json.dumps(
            {
                "case_id": case_id,
                "stored": stored,
                "problems": outcome.problems,
                "flags": [f"{f.code}: {f.detail}" for f in outcome.flags],
                "excluded_precedents": [o.precedent_id for o in outcome.overlaps],
                "memorization_probe": outcome.case.build.memorization_probe if outcome.case else None,
                "review_file": review.relative_to(REPO_ROOT).as_posix(),
            },
            indent=2,  # literal-ok: display indentation
            ensure_ascii=False,
        )
    )
    return 0 if stored else 1


def _show(case_id: str) -> int:
    with SealedProcess.from_env_files([DEFAULT_ENV_FILE, SEALED_ENV_FILE]) as proc:
        truth = proc.review().ground_truth.get_for_review(case_id)
    print(json.dumps(truth.to_document(), indent=2, ensure_ascii=False))  # literal-ok: display indentation
    return 0


def _approve(case_id: str, by: str) -> int:
    with SealedProcess.from_env_files([DEFAULT_ENV_FILE, SEALED_ENV_FILE]) as proc:
        cases = proc.clerk().cases
        case = cases.get(case_id)
        cases.put(case.model_copy(update={"build": case.build.model_copy(update={"human_reviewed": True})}))
    print(f"{case_id}: marked human-reviewed by {by}")
    return 0


def run(args: argparse.Namespace, config_path: Path) -> int:
    if args.action == "run":
        return _run(args.file, args.case_id, config_path)
    if args.action == "show":
        return _show(args.case_id)
    return _approve(args.case_id, args.by)
