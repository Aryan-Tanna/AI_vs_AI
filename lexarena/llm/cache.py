"""Response cache and usage tracking for LLM requests and agent runs.

Supports:
1. SQLite ResponseCache for LLMClient (upstream AI_vs_AI architecture).
2. Disk-backed CachedBackend for Session/Agent runner (simulation architecture).
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import TYPE_CHECKING, Any

from lexarena.llm.types import LLMRequest

if TYPE_CHECKING:
    from lexarena.config import Settings
    from lexarena.llm.agent import AgentResult, AgentSpec, Backend
    from lexarena.session.ledger import UsageLedger


def request_key(request: LLMRequest) -> str:
    """Everything that can change the output is in the key: provider, model, sampling, schema and messages."""
    payload = {
        "model": request.model.model_dump(exclude={"api_key_env"}),
        "seed": request.seed,
        "schema_name": request.schema_name,
        "schema": request.json_schema,
        "messages": [m.model_dump() for m in request.messages],
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


class ResponseCache:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(path)
        self._db.execute("CREATE TABLE IF NOT EXISTS responses (key TEXT PRIMARY KEY, text TEXT NOT NULL)")
        self._db.commit()

    def get(self, key: str) -> str | None:
        row = self._db.execute("SELECT text FROM responses WHERE key = ?", (key,)).fetchone()
        return None if row is None else str(row[0])

    def put(self, key: str, text: str) -> None:
        self._db.execute("INSERT OR REPLACE INTO responses (key, text) VALUES (?, ?)", (key, text))
        self._db.commit()

    def close(self) -> None:
        self._db.close()


def cache_key(spec: Any, model: str, prompt: str) -> str:
    payload = {
        "role": spec.role,
        "model": model,
        "system": spec.system_prompt,
        "prompt": prompt,
        "tools": sorted(t.name for t in spec.tools),
        "salt": spec.cache_salt,
        "builtin": sorted(spec.builtin_tools),
        "rules": sorted(spec.allow_rules),
        "mcp": sorted(spec.external_mcp),
        "schema": spec.output_model.model_json_schema() if spec.output_model else None,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


class CachedBackend:
    def __init__(self, inner: Any, settings: Any, ledger: Any):
        self.inner, self.settings, self.ledger = inner, settings, ledger
        self.dir: Path = settings.cache_dir
        self.dir.mkdir(parents=True, exist_ok=True)
        self.job_key: str | None = None  # set by the runner for ledger attribution

    async def run(self, spec: Any, prompt: str) -> Any:
        from lexarena.llm.agent import AgentResult

        model = spec.model or self.settings.role(spec.role).model
        path = self.dir / f"{cache_key(spec, model, prompt)}.json"
        if path.exists():
            res = AgentResult(**json.loads(path.read_text(encoding="utf-8")))
            res.cached = True
        else:
            res = await self.inner.run(spec, prompt)
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(res.to_dict(), ensure_ascii=False), encoding="utf-8")
            tmp.replace(path)
        self.ledger.call(spec.role, res.model, res.num_turns, res.usage, res.cost_usd, res.cached, self.job_key)
        return res
