"""SQLite response cache. Only schema-valid responses are stored."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

from lexarena.llm.types import LLMRequest


def request_key(request: LLMRequest) -> str:
    """Everything that can change the output is in the key: provider, model, sampling, schema and messages."""
    payload = {
        # Unset optional settings are left out, so adding one never changes the key of a model that does not use it.
        "model": request.model.model_dump(
            exclude={"api_key_env", "fallback_key_envs", "fallback_models"}, exclude_none=True
        ),
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
        columns = {row[1] for row in self._db.execute("PRAGMA table_info(responses)")}
        if "reasoning" not in columns:  # D-110: older caches have no reasoning; their entries just show none
            self._db.execute("ALTER TABLE responses ADD COLUMN reasoning TEXT")
        self._db.commit()

    def get(self, key: str) -> str | None:
        entry = self.get_entry(key)
        return None if entry is None else entry[0]

    def get_entry(self, key: str) -> tuple[str, str | None] | None:
        """The cached answer and the reasoning that came with it (None for entries cached before D-110)."""
        row = self._db.execute("SELECT text, reasoning FROM responses WHERE key = ?", (key,)).fetchone()
        return None if row is None else (str(row[0]), None if row[1] is None else str(row[1]))

    def put(self, key: str, text: str, reasoning: str | None = None) -> None:
        self._db.execute(
            "INSERT OR REPLACE INTO responses (key, text, reasoning) VALUES (?, ?, ?)", (key, text, reasoning)
        )
        self._db.commit()

    def close(self) -> None:
        self._db.close()
