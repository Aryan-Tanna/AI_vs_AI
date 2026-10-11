"""What produced a session (CLAUDE.md §10; ARCHITECTURE §7): code, config, Law DB, precedent DB and memory versions."""

from __future__ import annotations

import hashlib
import subprocess
from collections.abc import Mapping
from pathlib import Path

from lexarena.storage.temporal import StatuteView


def git_sha(repo: Path) -> str:
    """HEAD, with `-dirty` when tracked files have uncommitted changes."""

    def git(*args: str) -> str:
        done = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=False)
        return done.stdout.strip()

    sha = git("rev-parse", "HEAD") or "unknown"
    return f"{sha}-dirty" if git("status", "--porcelain", "--untracked-files=no") else sha


def combine(*parts: str) -> str:
    return hashlib.sha256("\n".join(parts).encode()).hexdigest()


def statute_version(view: StatuteView) -> str:
    """Which version of a provision a case saw (D-111): its Law DB record and the approved overlay values that applied
    on the case dates. Two cases with the same value saw the same law; lessons are pinned only where it matches."""
    applied = sorted((a.overlay_id, a.parameter, str(a.value)) for a in view.applied)
    payload = view.record.model_dump_json() + repr(applied) + view.in_force
    return hashlib.sha256(payload.encode()).hexdigest()


def law_versions(views: Mapping[str, StatuteView]) -> dict[str, str]:
    return {sid: statute_version(v) for sid, v in sorted(views.items())}


def precedent_snapshot(stored: dict[str, tuple[str, str | None]]) -> str:
    """A hash of every stored precedent's content and derived hashes (incremental ingestion keeps these current)."""
    return combine(*(f"{pid}:{c}:{d}" for pid, (c, d) in sorted(stored.items())))
