"""What produced a session (CLAUDE.md §10; ARCHITECTURE §7): code, config, Law DB, precedent DB and memory versions."""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path


def git_sha(repo: Path) -> str:
    """HEAD, with `-dirty` when tracked files have uncommitted changes."""

    def git(*args: str) -> str:
        done = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=False)
        return done.stdout.strip()

    sha = git("rev-parse", "HEAD") or "unknown"
    return f"{sha}-dirty" if git("status", "--porcelain", "--untracked-files=no") else sha


def combine(*parts: str) -> str:
    return hashlib.sha256("\n".join(parts).encode()).hexdigest()


def precedent_snapshot(stored: dict[str, tuple[str, str | None]]) -> str:
    """A hash of every stored precedent's content and derived hashes (incremental ingestion keeps these current)."""
    return combine(*(f"{pid}:{c}:{d}" for pid, (c, d) in sorted(stored.items())))
