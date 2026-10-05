"""Command line entry point: `lexarena --help`."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from lexarena.app import PROMPTS_ROOT, build_llm_client, configure_llm_logging
from lexarena.config import config_sha256, load_config
from lexarena.llm.errors import LLMError
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


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="lexarena")
    parser.add_argument("--config", help="config file (default: LEXARENA_CONFIG_PATH)")
    sub = parser.add_subparsers(dest="group", required=True)
    config_cmd = sub.add_parser("config").add_subparsers(dest="action", required=True)
    config_cmd.add_parser("show", help="print the resolved config summary and its hash")
    llm_cmd = sub.add_parser("llm").add_subparsers(dest="action", required=True)
    smoke = llm_cmd.add_parser("smoke", help="one real schema-validated call per role (spends quota)")
    smoke.add_argument("--role", action="append", help="limit to this role (repeatable)")
    args = parser.parse_args(argv)

    path = _config_path(args.config)
    if args.group == "config":
        return _config_show(path)
    return _llm_smoke(path, args.role)


if __name__ == "__main__":
    sys.exit(main())
