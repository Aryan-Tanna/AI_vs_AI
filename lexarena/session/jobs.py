"""Durable job queue (SQLite). Survives crashes, window resets and reboots.

States: pending -> running -> done | failed. A job interrupted by a usage limit is *released* back to
pending with its checkpoint intact and no attempt counted; the next window resumes it from the
last completed step.
"""
import json
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,
    key TEXT NOT NULL UNIQUE,          -- e.g. "debate:PC-0001:run1"; enqueue is idempotent on it
    payload TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT 'pending',
    attempts INTEGER NOT NULL DEFAULT 0,
    checkpoint TEXT NOT NULL DEFAULT '{}',
    result TEXT,
    error TEXT,
    updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS jobs_state ON jobs(state, id);
"""


@dataclass
class Job:
    id: int
    kind: str
    key: str
    payload: dict
    attempts: int
    checkpoint: dict


class JobQueue:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, isolation_level=None)   # autocommit; explicit BEGIN where needed
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript(SCHEMA)

    def close(self) -> None:
        self.db.close()

    def enqueue(self, kind: str, key: str, payload: dict) -> bool:
        cur = self.db.execute(
            "INSERT OR IGNORE INTO jobs(kind, key, payload, updated_at) VALUES (?,?,?,?)",
            (kind, key, json.dumps(payload, ensure_ascii=False), time.time()))
        return cur.rowcount == 1

    def recover(self) -> int:
        """Jobs left 'running' by a crashed process go back to pending (checkpoint kept)."""
        return self.db.execute("UPDATE jobs SET state='pending', updated_at=? WHERE state='running'",
                               (time.time(),)).rowcount

    def claim_next(self, kinds: list[str] | None = None) -> Job | None:
        self.db.execute("BEGIN IMMEDIATE")
        try:
            sql = "SELECT id, kind, key, payload, attempts, checkpoint FROM jobs WHERE state='pending'"
            args: list = []
            if kinds:
                sql += f" AND kind IN ({','.join('?' * len(kinds))})"
                args += kinds
            row = self.db.execute(sql + " ORDER BY id LIMIT 1", args).fetchone()
            if row is None:
                self.db.execute("COMMIT")
                return None
            self.db.execute("UPDATE jobs SET state='running', updated_at=? WHERE id=?", (time.time(), row[0]))
            self.db.execute("COMMIT")
        except Exception:
            self.db.execute("ROLLBACK")
            raise
        return Job(row[0], row[1], row[2], json.loads(row[3]), row[4], json.loads(row[5]))

    def save_checkpoint(self, job_id: int, checkpoint: dict) -> None:
        self.db.execute("UPDATE jobs SET checkpoint=?, updated_at=? WHERE id=?",
                        (json.dumps(checkpoint, ensure_ascii=False), time.time(), job_id))

    def complete(self, job_id: int, result: dict) -> None:
        self.db.execute("UPDATE jobs SET state='done', result=?, error=NULL, updated_at=? WHERE id=?",
                        (json.dumps(result, ensure_ascii=False), time.time(), job_id))

    def release(self, job_id: int) -> None:
        """Usage limit hit: back to pending, no attempt counted."""
        self.db.execute("UPDATE jobs SET state='pending', updated_at=? WHERE id=?", (time.time(), job_id))

    def fail(self, job_id: int, error: str, max_attempts: int) -> str:
        attempts = self.db.execute("SELECT attempts FROM jobs WHERE id=?", (job_id,)).fetchone()[0] + 1
        state = "failed" if attempts >= max_attempts else "pending"
        self.db.execute("UPDATE jobs SET state=?, attempts=?, error=?, updated_at=? WHERE id=?",
                        (state, attempts, error[:4000], time.time(), job_id))
        return state

    def counts(self) -> dict[str, dict[str, int]]:
        out: dict[str, dict[str, int]] = {}
        for kind, state, n in self.db.execute("SELECT kind, state, COUNT(*) FROM jobs GROUP BY kind, state"):
            out.setdefault(kind, {})[state] = n
        return out

    def failures(self, limit: int = 20) -> list[tuple[str, str]]:
        return self.db.execute("SELECT key, error FROM jobs WHERE state='failed' ORDER BY updated_at DESC LIMIT ?",
                               (limit,)).fetchall()
