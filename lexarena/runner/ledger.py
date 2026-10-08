"""The run's checkpoint on disk: `<runs_dir>/<run_id>/ledger.json` (D-073).

Every write goes to a temporary file that then replaces the ledger in one step, so a crash mid-write leaves the
previous ledger intact. A lock file keeps two run managers off the same run; a crashed manager leaves it behind, and
the operator removes it after checking that no manager is running.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from lexarena.schemas.run import RunLedger

LEDGER = "ledger.json"
LOCK = ".lock"
JSON_INDENT = 2  # literal-ok: file formatting


class RunLockedError(RuntimeError):
    """Another run manager holds this run, or a crashed one left its lock."""


class LedgerStore:
    def __init__(self, runs_dir: Path, run_id: str) -> None:
        self.dir = runs_dir / run_id
        self._path = self.dir / LEDGER

    def exists(self) -> bool:
        return self._path.is_file()

    def load(self) -> RunLedger:
        return RunLedger.model_validate_json(self._path.read_text(encoding="utf-8"))

    def save(self, ledger: RunLedger) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(ledger.model_dump_json(indent=JSON_INDENT) + "\n", encoding="utf-8")
        os.replace(tmp, self._path)

    def case_dir(self, case_id: str) -> Path:
        return self.dir / "cases" / case_id

    @contextmanager
    def locked(self) -> Iterator[None]:
        self.dir.mkdir(parents=True, exist_ok=True)
        lock = self.dir / LOCK
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError as exc:
            raise RunLockedError(f"{lock} exists: another run manager is active, or one crashed") from exc
        try:
            os.write(fd, str(os.getpid()).encode())
            os.close(fd)
            yield
        finally:
            lock.unlink(missing_ok=True)
