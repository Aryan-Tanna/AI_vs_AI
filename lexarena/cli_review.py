"""CLI for Step 3: register legal sources, draft side-collection items, review them, load approved ones.

    lexarena sources add --source-id ID --url URL --title T --issuer I --reference R --issued-on YYYY-MM-DD
    lexarena sources list
    lexarena draft overlay|predicate --statute STATUTE_ID --source SOURCE_ID --find TERM [--find TERM]
    lexarena review list [--status DRAFT|APPROVED|REJECTED]
    lexarena review show ID
    lexarena review approve ID --by NAME [--note TEXT]
    lexarena review reject ID --by NAME --reason TEXT
    lexarena review load

Approving is the reviewer's act (non-negotiable 8); Claude Code never runs `review approve`.
"""

from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path
from typing import Any

import httpx

from lexarena.app import DEFAULT_ENV_FILE, PROMPTS_ROOT, REPO_ROOT, SEALED_ENV_FILE, build_llm_client
from lexarena.config import load_config
from lexarena.drafting.draft import draft_overlay, draft_predicate
from lexarena.drafting.loader import load_approved
from lexarena.drafting.review import ReviewStore
from lexarena.drafting.sources import SourceMeta, SourceRegistry
from lexarena.prompts import PromptStore
from lexarena.storage.factory import SealedProcess

SOURCES_ROOT = REPO_ROOT / "data" / "legal_sources"
REVIEW_ROOT = REPO_ROOT / "review"
JSON_INDENT = 2  # literal-ok: display indentation


def _print(value: Any) -> None:
    print(json.dumps(value, indent=JSON_INDENT, ensure_ascii=False, default=str))


def add_parsers(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    sources = sub.add_parser("sources").add_subparsers(dest="action", required=True)
    add = sources.add_parser("add", help="download an official PDF and register it with pinned hashes")
    for name in ("--source-id", "--url", "--title", "--issuer", "--reference", "--issued-on"):
        add.add_argument(name, required=True)
    sources.add_parser("list", help="registered sources")

    draft = sub.add_parser("draft").add_subparsers(dest="action", required=True)
    for kind in ("overlay", "predicate"):
        cmd = draft.add_parser(kind, help=f"two-model draft of {kind} items into review/ (spends LLM quota)")
        cmd.add_argument("--statute", required=True)
        cmd.add_argument("--source", required=True)
        cmd.add_argument("--find", action="append", required=True, help="search term locating the provision")

    review = sub.add_parser("review").add_subparsers(dest="action", required=True)
    listing = review.add_parser("list")
    listing.add_argument("--status", choices=["DRAFT", "APPROVED", "REJECTED"])
    review.add_parser("show").add_argument("draft_id")
    approve = review.add_parser("approve")
    approve.add_argument("draft_id")
    approve.add_argument("--by", required=True)
    approve.add_argument("--note")
    reject = review.add_parser("reject")
    reject.add_argument("draft_id")
    reject.add_argument("--by", required=True)
    reject.add_argument("--reason", required=True)
    review.add_parser("load", help="load APPROVED items into MongoDB after re-verifying them")


def run(args: argparse.Namespace, config_path: Path) -> int:
    registry = SourceRegistry(SOURCES_ROOT)
    store = ReviewStore(REVIEW_ROOT)
    if args.group == "sources":
        if args.action == "list":
            _print([s.to_document() for s in registry.all()])
            return 0
        pdf = httpx.get(args.url, timeout=120, follow_redirects=True).raise_for_status().content  # literal-ok: seconds
        meta = SourceMeta(
            source_id=args.source_id,
            title=args.title,
            issuer=args.issuer,
            reference=args.reference,
            issued_on=date.fromisoformat(args.issued_on),
            url=args.url,
        )
        _print(registry.register(pdf, meta).to_document())
        return 0

    if args.group == "draft":
        cfg = load_config(config_path)
        with SealedProcess.from_env_files([DEFAULT_ENV_FILE, SEALED_ENV_FILE]) as proc:
            record = proc.ingest().law.get_record(args.statute)
        if record is None:
            raise SystemExit(f"{args.statute} is not in the loaded Law DB (run lexarena law load)")
        llm = build_llm_client(cfg)
        drafter = draft_overlay if args.action == "overlay" else draft_predicate
        drafts = drafter(llm, cfg, PromptStore(PROMPTS_ROOT), record, registry, args.source, args.find)
        _print([{"draft_id": d.draft_id, "new": store.save(d), "agreement": d.agreement,
                 "blocking_problems": d.blocking_problems} for d in drafts])  # fmt: skip
        return 0

    if args.action == "list":
        _print([
            {"draft_id": d.draft_id, "kind": d.kind, "statute_id": d.statute_id, "status": d.status,
             "agreement": d.agreement, "blocking": len(d.blocking_problems)}
            for d in store.all() if args.status in (None, d.status)
        ])  # fmt: skip
        return 0
    if args.action == "show":
        _print(store.get(args.draft_id).to_document())
        return 0
    if args.action == "approve":
        _print(store.approve(args.draft_id, by=args.by, note=args.note).to_document())
        return 0
    if args.action == "reject":
        _print(store.reject(args.draft_id, by=args.by, reason=args.reason).to_document())
        return 0
    cfg = load_config(config_path)
    with SealedProcess.from_env_files([DEFAULT_ENV_FILE, SEALED_ENV_FILE]) as proc:
        report = load_approved(store, registry, proc.ingest().law, cfg.vocabulary)
    _print(report.model_dump())
    return 1 if report.skipped else 0
