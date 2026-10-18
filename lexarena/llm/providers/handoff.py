"""File-exchange provider (D-127, pilot only): the request is written to `<key>.prompt.json` in the exchange folder and
answered by a Claude Code agent in `<key>.answer.json`. The answer then goes through the client exactly like a
provider's: schema validation (and its repair round, which is a new request), the cache and the call log.

The folder holds clerk prompts, which carry real names: it must stay git-ignored (`.cache/`).
"""

from __future__ import annotations

import json
from pathlib import Path

from lexarena.llm.cache import request_key
from lexarena.llm.errors import HandoffPendingError
from lexarena.llm.types import LLMRequest, LLMResponse
from lexarena.schemas.config import HandoffProviderConfig

PROMPT_SUFFIX, ANSWER_SUFFIX = ".prompt.json", ".answer.json"
FINISH = "handoff"


def pending_prompts(folder: Path) -> list[Path]:
    """Prompt files whose answer file is not written yet, oldest first."""
    if not folder.is_dir():
        return []
    prompts = [p for p in folder.glob(f"*{PROMPT_SUFFIX}") if not _answer_path(p).exists()]
    return sorted(prompts, key=lambda p: p.stat().st_mtime)


def _answer_path(prompt: Path) -> Path:
    return prompt.with_name(prompt.name.removesuffix(PROMPT_SUFFIX) + ANSWER_SUFFIX)


class HandoffProvider:
    needs_key = False

    def __init__(self, config: HandoffProviderConfig, root: Path | None = None) -> None:
        folder = Path(config.exchange_dir)
        self._folder = folder if folder.is_absolute() or root is None else root / folder

    def complete(self, request: LLMRequest, api_key: str) -> LLMResponse:
        key = request_key(request)
        prompt = self._folder / f"{key}{PROMPT_SUFFIX}"
        answer = _answer_path(prompt)
        if answer.is_file():
            return LLMResponse(
                text=answer.read_text(encoding="utf-8"), input_tokens=None, output_tokens=None, finish_reason=FINISH
            )
        self._folder.mkdir(parents=True, exist_ok=True)
        body = {
            "schema_name": request.schema_name,
            "json_schema": request.json_schema,
            "messages": [m.model_dump() for m in request.messages],
            "answer_file": answer.resolve().as_posix(),
        }
        prompt.write_text(json.dumps(body, ensure_ascii=False, indent=1), encoding="utf-8")
        raise HandoffPendingError(f"answer needed: {prompt.resolve().as_posix()}", prompt_file=prompt.as_posix())
