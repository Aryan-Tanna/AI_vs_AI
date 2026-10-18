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
import re
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
from lexarena.clerk.checks import REGISTRATION_NUMBER
from lexarena.clerk.names import EMAIL_OR_DOMAIN, residual_names
from lexarena.clerk.pipeline import clerk_judgment
from lexarena.clerk.redact import drop_key_dates, redact_view
from lexarena.clerk.review import render_review
from lexarena.clerk.text import BLOCK_MARK
from lexarena.config import load_config
from lexarena.drafting.pdf import pdf_pages_blocks
from lexarena.llm.errors import HandoffPendingError
from lexarena.prompts import PromptStore
from lexarena.schemas.case import ExtractionFlag
from lexarena.schemas.clerk import NamedEntity
from lexarena.schemas.config import HANDOFF_ROLES
from lexarena.statute_ids import load_statute_aliases
from lexarena.storage.errors import SealedError
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
    run.add_argument(
        "--handoff",
        action="store_true",
        help="pilot only (D-127): a Claude Code agent answers the primary and extractor prompts through files",
    )
    run.add_argument(
        "--handoff-role",
        action="append",
        choices=HANDOFF_ROLES,
        help="with --handoff: only these roles (repeatable; default both), keeping the other's cached answers (D-131)",
    )
    show = clerk.add_parser("show", help="the sealed record, through the REVIEW role, before the first session")
    show.add_argument("case_id")
    approve = clerk.add_parser("approve", help="mark a clerked case as reviewed by you")
    approve.add_argument("case_id")
    approve.add_argument("--by", required=True)
    redact = clerk.add_parser(
        "redact", help="replace a leak in a stored agent view by its pseudonym or a mask, then re-check (D-129)"
    )
    redact.add_argument("case_id")
    redact.add_argument(
        "--replace",
        nargs=2,  # literal-ok: a (text, token) pair
        action="append",
        default=[],
        metavar=("TEXT", "TOKEN"),
        help="repeatable",
    )
    redact.add_argument(
        "--drop-key-date", action="append", default=[], metavar="LABEL", help="a key date of another proceeding (D-133)"
    )
    triage = clerk.add_parser(
        "triage", help="record that Claude Code checked the split and found nothing blocking (never the owner's review)"
    )
    triage.add_argument("case_id")
    triage.add_argument("--report", type=Path, required=True, help="the check_split report the triage rests on")


def _manifest_entry(pdf: Path) -> dict[str, Any]:
    rel = pdf.resolve().relative_to(DEV_ROOT.resolve()).as_posix()
    files: list[dict[str, Any]] = json.loads((DEV_ROOT / "dev_cases.json").read_text(encoding="utf-8"))["files"]
    entry = next((f for f in files if f["file"] == rel), None)
    if entry is None:
        raise SystemExit(f"{rel} is not listed in data/dev/dev_cases.json")
    if entry["status"] not in CLERKABLE or entry.get("decided") is None:
        raise SystemExit(f"{rel} is {entry['status']}: not a case to clerk")
    return entry


HANDOFF_PENDING = 3  # literal-ok: process exit code, a prompt is waiting for its answer file (D-127)
HANDOFF_FLAG = ExtractionFlag(
    code="CLERKED_BY_CLAUDE",
    detail="names, routing, record facts, agent view and ground truth answered by Claude Code (D-127, pilot only)",
    resolution="Claude also triages: the owner spot-checks this case against the judgment before it teaches",
)


def _run(pdf: Path, case_id: str, config_path: Path, *, handoff: bool = False, roles: list[str] | None = None) -> int:
    cfg = load_config(config_path)
    if roles and not handoff:
        raise SystemExit("--handoff-role needs --handoff")
    if handoff:
        cfg = cfg.with_clerk_handoff(tuple(roles) if roles else HANDOFF_ROLES)
    configure_llm_logging(cfg)
    entry = _manifest_entry(pdf)
    data = pdf.read_bytes()
    pages = pdf_pages_blocks(data, BLOCK_MARK)
    with SealedProcess.from_env_files([DEFAULT_ENV_FILE, SEALED_ENV_FILE]) as proc:
        stores = proc.clerk()
        try:
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
        except HandoffPendingError as exc:
            # Only this run's prompt: the folder is shared by cases clerked in parallel, and listing every pending
            # prompt led an agent to answer another case's (D-134).
            prompt = Path(exc.prompt_file)
            shown = (prompt if prompt.is_absolute() else REPO_ROOT / prompt).as_posix()
            print(json.dumps({"case_id": case_id, "stored": False, "handoff_pending": [shown]}))
            return HANDOFF_PENDING
        if handoff and outcome.case is not None:
            build = outcome.case.build
            outcome.case = outcome.case.model_copy(
                update={"build": build.model_copy(update={"extraction_flags": [*build.extraction_flags, HANDOFF_FLAG]})}
            )
            outcome.flags.append(HANDOFF_FLAG)
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


def _redact(case_id: str, replacements: list[tuple[str, str]], config_path: Path, drop: list[str] | None = None) -> int:
    """D-129: a triage leak fixed without re-clerking. Only this case's pseudonyms or a mask can be written; the leak
    checks run again (names only while the review window is open); the flag never repeats the replaced text."""
    cfg = load_config(config_path)
    with SealedProcess.from_env_files([DEFAULT_ENV_FILE, SEALED_ENV_FILE]) as proc:
        cases = proc.clerk().cases
        case = cases.get(case_id)
        view = case.agent_view
        text = view.model_dump_json()
        allowed = {p.pseudonym for p in view.parties} | set(
            re.findall(r"\b(?:Person|Company|Bank|Authority|Entity)-[A-Z]{1,2}\b", text)
        )
        if not replacements and not drop:
            raise SystemExit("nothing to do: give --replace and/or --drop-key-date")
        new_view, touched = redact_view(view, replacements, allowed=allowed) if replacements else (view, [])
        if drop:
            new_view = drop_key_dates(new_view, drop)
            touched.append(f"metadata.key_dates (dropped {sorted(drop)})")
        out = new_view.model_dump_json()
        problems = [f"registration number: {h}" for h in REGISTRATION_NUMBER.findall(out)]
        problems += [f"address: {h}" for h in EMAIL_OR_DOMAIN.findall(out)]
        try:
            truth = proc.review().ground_truth.get_for_review(case_id)
        except SealedError:
            names_checked = False
        else:
            names_checked = True
            entities = [
                NamedEntity(name=n, variants=[], kind="OTHER", cause_title_role=None)
                for n in truth.anonymization_map.values()
            ]
            problems += [f"real name: {h}" for h in residual_names(out, entities, cfg.clerk.generic_name_words)]
        if problems:
            print(json.dumps({"case_id": case_id, "redacted": False, "problems": problems}, ensure_ascii=False))
            return 1
        flag = ExtractionFlag(
            code="REDACTED_AFTER_CLERK",
            detail=f"{len(replacements)} leak(s) replaced by {sorted({t for _, t in replacements})} in {touched}",
            resolution="redaction only (D-129): no content added; leak checks re-run"
            + ("" if names_checked else "; names not re-checked (review window closed)"),
        )
        build = case.build.model_copy(update={"extraction_flags": [*case.build.extraction_flags, flag]})
        cases.put(case.model_copy(update={"agent_view": new_view, "build": build}))
    print(json.dumps({"case_id": case_id, "redacted": True, "fields": touched, "names_checked": names_checked}))
    return 0


def _triage(case_id: str, report: Path) -> int:
    """D-114: kept apart from `approve`; whether a triaged case may teach lessons is `memory.accept_claude_triage`."""
    if not report.is_file():
        raise SystemExit(f"{report}: no such report; run scripts/check_split.py first")
    with SealedProcess.from_env_files([DEFAULT_ENV_FILE, SEALED_ENV_FILE]) as proc:
        cases = proc.clerk().cases
        case = cases.get(case_id)
        cases.put(case.model_copy(update={"build": case.build.model_copy(update={"claude_triaged": True})}))
    print(f"{case_id}: marked Claude-triaged on {report}")
    return 0


def run(args: argparse.Namespace, config_path: Path) -> int:
    if args.action == "run":
        return _run(args.file, args.case_id, config_path, handoff=args.handoff, roles=args.handoff_role)
    if args.action == "show":
        return _show(args.case_id)
    if args.action == "redact":
        return _redact(args.case_id, [tuple(r) for r in args.replace], config_path, args.drop_key_date)
    if args.action == "triage":
        return _triage(args.case_id, args.report)
    return _approve(args.case_id, args.by)
