"""What each stage runs (BUILD_PLAN Step 13; D-034, D-073).

Every stage is a `lexarena` subprocess, never a function call, because the stages need different credentials: the
session and the baseline run with session secrets only, the evaluator with the sealed ones (D-034). The run manager's
own process holds neither sealed credentials nor any repository of sealed data.

A stage with no command is NOT_BUILT: SESSION until the orchestrator exists (Step 9; it must print a final JSON line
with `session_id`), REFLECT until reflection exists (Q-032).
"""

from __future__ import annotations

import json
import subprocess
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from lexarena.schemas.run import Stage

SESSION_ID = "session_id"


@dataclass(frozen=True)
class StageSpec:
    stage: Stage
    argv: tuple[str, ...] | None  # `lexarena` arguments with {placeholders}; None: not built yet
    needs: tuple[str, ...] = ()  # outputs of earlier stages this one needs (else it is SKIPPED)
    files: Mapping[str, str] = field(default_factory=dict)  # output name -> file the stage writes


DEFAULT_SPECS: dict[Stage, StageSpec] = {
    "SESSION": StageSpec("SESSION", None),
    "BASELINE": StageSpec(
        "BASELINE",
        ("baseline", "single", "--case-id", "{case_id}", "--out", "{case_dir}/baseline.json"),
        files={"baseline": "{case_dir}/baseline.json"},
    ),
    "EVALUATE": StageSpec(
        "EVALUATE",
        (
            "evaluate",
            "session",
            "{session_id}",
            "--baseline",
            "{case_dir}/baseline.json",
            "--out",
            "{case_dir}/outcome.json",
        ),
        needs=(SESSION_ID,),
        files={"outcome": "{case_dir}/outcome.json"},
    ),
    "REFLECT": StageSpec("REFLECT", None, needs=(SESSION_ID,)),
}


@dataclass(frozen=True)
class ExecResult:
    code: int
    stdout: str
    stderr: str


class Executor(Protocol):
    def run(self, argv: Sequence[str]) -> ExecResult: ...


class SubprocessExecutor:
    """Runs `python -m lexarena.cli --config <config> <argv>` with the same interpreter and environment."""

    def __init__(self, config_path: Path, cwd: Path, timeout_s: float) -> None:
        self._config = config_path
        self._cwd = cwd
        self._timeout = timeout_s

    def run(self, argv: Sequence[str]) -> ExecResult:
        cmd = [sys.executable, "-m", "lexarena.cli", "--config", str(self._config), *argv]
        done = subprocess.run(
            cmd, cwd=self._cwd, capture_output=True, text=True, encoding="utf-8", timeout=self._timeout, check=False
        )
        return ExecResult(done.returncode, done.stdout, done.stderr)


def render(spec: StageSpec, values: Mapping[str, str]) -> list[str]:
    assert spec.argv is not None
    return [part.format(**values) for part in spec.argv]


def last_json(stdout: str) -> dict[str, str]:
    """The stage's final JSON line, as string outputs; {} when there is none."""
    for line in reversed(stdout.strip().splitlines()):
        try:
            value = json.loads(line)
        except ValueError:
            continue
        if isinstance(value, dict):
            return {str(k): str(v) for k, v in value.items() if v is not None}
    return {}
