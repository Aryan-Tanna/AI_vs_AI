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
