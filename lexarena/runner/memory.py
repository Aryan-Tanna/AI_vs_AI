"""Memory modes and the proof that a frozen run writes nothing (ARCHITECTURE §7; SPEC G1; D-073).

- LEARN: reflection runs after each evaluated case; lessons from case N are readable from case N+1.
- FROZEN: memory is read but never written (validation and test runs). Reflection never runs.
- EMPTY: memory is neither read nor written (the empty-memory baseline). Reflection never runs.

The proof is a snapshot comparison: the run manager records the memory snapshot before and after every case, and in
FROZEN and EMPTY modes any change fails the run (FrozenMemoryViolation). The snapshot comes from the memory store
itself (`MemoryStore.snapshot`), so it covers writes from anywhere, not only from the stages the runner started.

The experience memories are built with reflection (Step 12, Q-032). Until then `NoMemory` stands in: an empty store
whose snapshot never changes.
"""

from __future__ import annotations

from typing import Protocol

from lexarena.schemas.run import MemoryMode, Stage

EMPTY_SNAPSHOT = "MEMORY_NOT_BUILT"


class FrozenMemoryViolationError(RuntimeError):
    """Memory changed during a case of a FROZEN or EMPTY run."""


class MemoryStore(Protocol):
    def snapshot(self) -> str:
        """A content hash of both experience memories; equal snapshots mean nothing was written."""
        ...


class NoMemory:
    def snapshot(self) -> str:
        return EMPTY_SNAPSHOT


def stage_allowed(stage: Stage, mode: MemoryMode) -> bool:
    """Reflection writes memory, so it runs only in LEARN mode."""
    return stage != "REFLECT" or mode == "LEARN"


def check_unchanged(mode: MemoryMode, case_id: str, before: str, after: str) -> None:
    if mode != "LEARN" and before != after:
        raise FrozenMemoryViolationError(
            f"memory changed during {case_id} in a {mode} run ({before} -> {after}); the run is invalid"
        )
