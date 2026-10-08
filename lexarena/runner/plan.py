"""Which cases a run takes, in what order, and which split each belongs to (ARCHITECTURE §7; SPEC G1, I3-2; D-073).

- Order: by decision date, then case ID, so the order is total and reproducible.
- Splits (`assign_splits`): the newest `splits.test_count` cases are TEST, the `splits.validation_count` before them
  VALIDATION, the rest TRAIN; then every dispute group (cases about the same corporate debtor or dispute, SPEC I3-2)
  goes whole into the latest split any of its cases reached, so no group straddles train and test. Group keys are
  computed where real names may be read (the clerk, offline); this module only sees opaque keys.
- Guards: a run may include only splits `runner.allowed_splits` permits (DEV until Phase 2 starts: the 500 are a red
  line, CLAUDE.md §5.4), and a LEARN run never includes TEST cases (test memory is frozen, SPEC G1).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

from lexarena.schemas.case import Split
from lexarena.schemas.config import RunnerConfig, SplitsConfig
from lexarena.schemas.run import MemoryMode

SPLIT_RANK: dict[Split, int] = {"TRAIN": 0, "VALIDATION": 1, "TEST": 2}  # literal-ok: ordering of splits by time


class PlanRefusedError(ValueError):
    """A run that would break a red line or the split protocol."""


@dataclass(frozen=True)
class CaseRef:
    case_id: str
    split: Split
    decided_on: date


def run_order(cases: Sequence[CaseRef]) -> list[CaseRef]:
    return sorted(cases, key=lambda c: (c.decided_on, c.case_id))


def check_plan(cases: Sequence[CaseRef], mode: MemoryMode, cfg: RunnerConfig, requested: Sequence[str] = ()) -> None:
    """`requested`: the splits the operator asked for; refused even when no case of them exists yet."""
    barred = sorted(({c.split for c in cases} | set(requested)) - set(cfg.allowed_splits))
    if barred:
        raise PlanRefusedError(
            f"splits {barred} are not allowed (runner.allowed_splits = {cfg.allowed_splits}); "
            "running the 500 needs the owner to start Phase 2 (CLAUDE.md §5.4)"
        )
    if mode == "LEARN" and any(c.split == "TEST" for c in cases):
        raise PlanRefusedError("a LEARN run never includes TEST cases: test memory is frozen (SPEC G1)")
    if len({c.case_id for c in cases}) != len(cases):
        raise PlanRefusedError("a case appears twice in the plan")
    if not cases:
        raise PlanRefusedError("the plan has no cases")


def assign_splits(dated: Sequence[tuple[str, date, str]], cfg: SplitsConfig) -> dict[str, Split]:
    """`dated`: (case_id, decision date, dispute group key). Returns the split of every case."""
    ordered = sorted(dated, key=lambda d: (d[1], d[0]))
    n = len(ordered)
    test_from = max(0, n - cfg.test_count)
    val_from = max(0, test_from - cfg.validation_count)
    split: dict[str, Split] = {}
    for i, (case_id, _, _) in enumerate(ordered):
        split[case_id] = "TEST" if i >= test_from else "VALIDATION" if i >= val_from else "TRAIN"
    latest: dict[str, Split] = {}
    for case_id, _, group in ordered:
        if group not in latest or SPLIT_RANK[split[case_id]] > SPLIT_RANK[latest[group]]:
            latest[group] = split[case_id]
    return {case_id: latest[group] for case_id, _, group in ordered}
