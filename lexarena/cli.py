"""Command line entry point: `lexarena --help`."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from lexarena import exit_codes
from lexarena.app import (
    DEFAULT_ENV_FILE,
    PROMPTS_ROOT,
    REPO_ROOT,
    SEALED_ENV_FILE,
    build_llm_client,
    configure_llm_logging,
)
from lexarena.config import config_sha256, load_config
from lexarena.llm.errors import LLMError, RateLimitedError
from lexarena.prompts import PromptStore
from lexarena.settings import Settings


class SmokeAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    answer: int
    unit: str


def _config_path(arg: str | None) -> Path:
    return Path(arg) if arg else Settings().config_path


def _config_show(path: Path) -> int:
    cfg = load_config(path)
    out = {
        "version": cfg.version,
        "config_path": str(path),
        "config_sha256": config_sha256(path),
        "providers": sorted(cfg.providers),
        "models": {role: m.model_dump() for role, m in cfg.models.by_role().items()},
        "seed": cfg.seed,
    }
    print(json.dumps(out, indent=2))  # literal-ok: display indentation
    return 0


def _llm_smoke(path: Path, roles: list[str] | None) -> int:
    cfg = load_config(path)
    configure_llm_logging(cfg)
    client = build_llm_client(cfg, use_cache=False)
    prompt = PromptStore(PROMPTS_ROOT).render(cfg.prompts.smoke.id, cfg.prompts.smoke.version)
    failures = 0
    for role in roles or list(cfg.models.by_role()):
        model = cfg.models.by_role()[role]
        try:
            result = client.complete_json(role=role, user=prompt, schema=SmokeAnswer, session_id=f"smoke-{role}")
            print(
                json.dumps(
                    {
                        "role": role,
                        "provider": model.provider,
                        "model": model.name,
                        "value": result.value.model_dump(),
                        "attempts": result.attempts,
                        "input_tokens": result.input_tokens,
                        "output_tokens": result.output_tokens,
                    }
                )
            )
        except LLMError as exc:
            failures += 1
            print(json.dumps({"role": role, "model": model.name, "error": type(exc).__name__, "detail": str(exc)}))
    return 1 if failures else 0


def _law(action: str, source: Path) -> int:
    from lexarena.ingest.law_db import load_law_db, read_law_sources, validate_law_db
    from lexarena.storage.factory import SealedProcess

    report = validate_law_db(*read_law_sources(source), source=str(source))
    out: dict[str, object] = {"report": report.model_dump(mode="json")}
    if action == "load":
        if not report.loadable:
            print(json.dumps(out, indent=2, ensure_ascii=False))  # literal-ok: display indentation
            return 1
        with SealedProcess.from_env_files([DEFAULT_ENV_FILE, SEALED_ENV_FILE]) as proc:
            result = load_law_db(proc.ingest().law, report)
        out["loaded"] = vars(result)
    print(json.dumps(out, indent=2, ensure_ascii=False))  # literal-ok: display indentation
    return 0 if report.loadable else 1


def _precedents(action: str, source: Path, aliases_path: Path, config_path: Path) -> int:
    from lexarena.embedding import FastEmbedder
    from lexarena.ingest.precedents import ingest_precedents, prepare_precedents, read_precedent_sources
    from lexarena.statute_ids import load_statute_aliases, missing_alias_targets
    from lexarena.storage.factory import SealedProcess

    cfg = load_config(config_path).embedding
    embedder = FastEmbedder(cfg.model, REPO_ROOT / cfg.cache_dir, cfg.batch_size)
    with SealedProcess.from_env_files([DEFAULT_ENV_FILE, SEALED_ENV_FILE]) as proc:
        stores = proc.ingest()
        known = stores.law.statute_ids()
        if not known:
            raise SystemExit("the Law DB is empty; run lexarena law load first")
        aliases = load_statute_aliases(aliases_path)
        prepared = prepare_precedents(
            *read_precedent_sources(source), known, embedder, cfg.window_tokens, cfg.max_tokens, aliases
        )
        out: dict[str, object] = {
            "report": prepared.report.model_dump(mode="json"),
            "alias_targets_matching_no_law_db_id": missing_alias_targets(aliases, known),
        }
        if action == "load":
            out["loaded"] = vars(ingest_precedents(stores.precedents, prepared, embedder))
    print(json.dumps(out, indent=2, ensure_ascii=False))  # literal-ok: display indentation
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):  # legal sources quote non-Latin text; a Windows console defaults to cp1252
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(prog="lexarena")
    parser.add_argument("--config", help="config file (default: LEXARENA_CONFIG_PATH)")
    sub = parser.add_subparsers(dest="group", required=True)
    config_cmd = sub.add_parser("config").add_subparsers(dest="action", required=True)
    config_cmd.add_parser("show", help="print the resolved config summary and its hash")
    llm_cmd = sub.add_parser("llm").add_subparsers(dest="action", required=True)
    smoke = llm_cmd.add_parser("smoke", help="one real schema-validated call per role (spends quota)")
    smoke.add_argument("--role", action="append", help="limit to this role (repeatable)")
    law_cmd = sub.add_parser("law").add_subparsers(dest="action", required=True)
    for action, text in (("validate", "validation report only"), ("load", "validate, then load into MongoDB")):
        cmd = law_cmd.add_parser(action, help=text)
        cmd.add_argument("--source", type=Path, default=REPO_ROOT / "data" / "law_db", help="folder of Law DB files")
    prec_cmd = sub.add_parser("precedents").add_subparsers(dest="action", required=True)
    for action, text in (("validate", "report only"), ("load", "validate, embed and load into Qdrant (incremental)")):
        cmd = prec_cmd.add_parser(action, help=text)
        cmd.add_argument("--source", type=Path, default=REPO_ROOT / "data" / "precedents", help="precedent folder")
        cmd.add_argument(
            "--aliases", type=Path, default=REPO_ROOT / "data" / "statute_aliases.json", help="statute alias table"
        )
    from lexarena import cli_clerk, cli_evaluate, cli_judges, cli_review, cli_run

    cli_review.add_parsers(sub)
    cli_clerk.add_parsers(sub)
    cli_judges.add_parsers(sub)
    cli_evaluate.add_parsers(sub)
    cli_run.add_parsers(sub)
    args = parser.parse_args(argv)
    try:
        return _dispatch(args)
    except RateLimitedError as exc:  # the run manager pauses on this code and resumes later (D-073)
        print(json.dumps({"error": "RATE_LIMITED", "detail": str(exc)}), file=sys.stderr)
        return exit_codes.QUOTA_EXHAUSTED


def _dispatch(args: argparse.Namespace) -> int:
    from lexarena import cli_clerk, cli_evaluate, cli_judges, cli_review, cli_run

    path = _config_path(args.config)
    if args.group == "config":
        return _config_show(path)
    if args.group == "law":
        return _law(args.action, args.source)
    if args.group == "precedents":
        return _precedents(args.action, args.source, args.aliases, path)
    if args.group in ("sources", "draft", "review"):
        return cli_review.run(args, path)
    if args.group == "clerk":
        return cli_clerk.run(args, path)
    if args.group == "judges":
        return cli_judges.run(args, path)
    if args.group in ("evaluate", "baseline", "reflect"):
        return cli_evaluate.run(args, path)
    if args.group == "run":
        return cli_run.run(args, path)
    return _llm_smoke(path, args.role)


if __name__ == "__main__":
    sys.exit(main())
