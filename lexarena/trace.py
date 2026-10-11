"""The session trace: everything that happened in one session, in order, for the owner's courtroom viewer (D-110).

One JSON line per record in `<trace.dir>/<session_id>.jsonl`:
- `llm`: one model call (role, schema, model, tokens, latency, whether cached), its parsed answer and, when the
  provider returns it, the model's reasoning text;
- `event`: what the orchestrator did (case opened, turn published, THEMIS outcome, verdict, evaluation).
Each record carries the tags active when it was written (phase, side, turn, attempt, persona, order).

Tracing happens only inside `session_trace(...)`, which only the session orchestrator (and the post-verdict evaluator
appending its result) opens. The clerk never opens one, so clerk prompts and answers, which carry real names, are never
traced. The files live under the git-ignored runs directory, and no agent, THEMIS or judge has a tool that reads files:
the trace is for the owner, never an input to any model.
"""

from __future__ import annotations

import itertools
import json
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SUFFIX = ".jsonl"


@dataclass
class _Scope:
    path: Path
    session_id: str
    tags: dict[str, Any] = field(default_factory=dict)
    counter: itertools.count[int] = field(default_factory=itertools.count)


_scope: ContextVar[_Scope | None] = ContextVar("lexarena_trace_scope", default=None)


def trace_path(trace_dir: Path, session_id: str) -> Path:
    return trace_dir / f"{session_id}{SUFFIX}"


def _write(scope: _Scope, record: dict[str, Any]) -> None:
    scope.path.parent.mkdir(parents=True, exist_ok=True)
    line = {
        "seq": next(scope.counter),
        "ts": datetime.now(UTC).isoformat(),
        "session_id": scope.session_id,
        **{k: v for k, v in scope.tags.items() if v is not None},
        **record,
    }
    with scope.path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(line, ensure_ascii=False, default=str) + "\n")


@contextmanager
def session_trace(trace_dir: Path | None, session_id: str) -> Iterator[None]:
    """Open the trace of one session; a None directory (tracing off) opens nothing."""
    if trace_dir is None:
        yield
        return
    path = trace_path(trace_dir, session_id)
    start = 0
    if path.is_file():  # an appended part (e.g. the evaluation) continues the numbering
        start = sum(1 for _ in path.open(encoding="utf-8"))
    token = _scope.set(_Scope(path=path, session_id=session_id, counter=itertools.count(start)))
    try:
        yield
    finally:
        _scope.reset(token)


@contextmanager
def tags(**values: Any) -> Iterator[None]:
    """Tag every record written inside the block (nested blocks add to the outer tags)."""
    scope = _scope.get()
    if scope is None:
        yield
        return
    before = dict(scope.tags)
    scope.tags.update(values)
    try:
        yield
    finally:
        scope.tags = before


def event(name: str, **data: Any) -> None:
    scope = _scope.get()
    if scope is not None:
        _write(scope, {"kind": "event", "event": name, **data})


def llm_call(session_id: str, **data: Any) -> None:
    """Called by the LLM client for every call; written only for the session whose trace is open."""
    scope = _scope.get()
    if scope is not None and scope.session_id == session_id:
        _write(scope, {"kind": "llm", **data})


def active() -> bool:
    return _scope.get() is not None
