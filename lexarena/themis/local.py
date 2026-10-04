"""THEMIS-LOCAL control flow: a two-stage gate per turn (CLAUDE.md §8.3).

    extract (Haiku) -> Stage A: code + rules + Z3, up to 3 attempts (advocate revises, Haiku re-extracts)
                    -> Stage B: LLM semantic checks, once, on the final version — whether or not A passed

Stage B never sends the turn back to Stage A: its findings are published as flags, not fixed. It runs
after the Stage A loop (not in parallel) because a Stage A revision changes the text, and Stage B
results on an earlier version would be stale or need re-running — costing subscription usage.

The checks themselves are injected (`Checkers`), so this module fixes the order, retry limit and
publishing rules, and the checks can be built and tested separately. Every model call (extract, revise,
Stage B) goes through `ctx.step`, so an interrupted gate resumes without repeating calls.
"""
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Literal

Stage = Literal["A", "B"]
Status = Literal["PASSED", "FLAGGED_HARD", "FLAGGED_SOFT", "FLAGGED_BOTH"]


@dataclass
class Finding:
    code: str            # e.g. ERR_FACT_MISMATCH, ERR_MISATTRIBUTED_RATIO
    claim: str           # the claim as extracted
    evidence: str        # record span / computed value / stored proposition
    stage: Stage

    def to_dict(self) -> dict:
        return self.__dict__.copy()


@dataclass
class Checkers:
    extract: Callable[[dict], Awaitable[dict]]                      # turn -> ClaimSet JSON (Haiku)
    stage_a: Callable[[dict], list[Finding]]                         # ClaimSet -> findings (code + Z3, no LLM)
    stage_b: Callable[[dict, dict], Awaitable[list[Finding]]]        # (turn, ClaimSet) -> findings (LLM)
    revise: Callable[[dict, list[Finding], int], Awaitable[dict]]    # (turn, findings, n) -> revised turn (same advocate)


@dataclass
class GateResult:
    turn: dict
    claims: dict
    status: Status
    flags: list[Finding]          # final Stage A findings (if A never passed) + Stage B findings
    stage_a_attempts: int
    log: list[dict] = field(default_factory=list)   # every attempt, for THEMIS-GLOBAL and the metrics

    def to_dict(self) -> dict:
        return {"turn": self.turn, "claims": self.claims, "status": self.status,
                "stage_a_attempts": self.stage_a_attempts, "flags": [f.to_dict() for f in self.flags],
                "log": self.log}


Step = Callable[[str, Callable[[], Awaitable[Any]]], Awaitable[Any]]


async def _no_checkpoint(_name: str, fn: Callable[[], Awaitable[Any]]) -> Any:
    return await fn()


async def _stage_b(step: Step, name: str, checks: Checkers, turn: dict, claims: dict) -> list[Finding]:
    """Checkpoints are JSON, so findings cross the step boundary as dicts."""
    async def call() -> list[dict]:
        return [f.to_dict() for f in await checks.stage_b(turn, claims)]
    return [Finding(**d) for d in await step(name, call)]


async def verify_turn(draft: dict, checks: Checkers, step: Step = _no_checkpoint, prefix: str = "themis",
                      max_stage_a_attempts: int = 3) -> GateResult:
    log: list[dict] = []

    # Stage A: deterministic. Fail -> same advocate revises -> Haiku re-extracts -> check again.
    turn = draft
    for attempt in range(1, max_stage_a_attempts + 1):
        claims = await step(f"{prefix}/extract_{attempt}", lambda: checks.extract(turn))
        hard = checks.stage_a(claims)
        log.append({"stage": "A", "attempt": attempt, "findings": [f.to_dict() for f in hard]})
        if not hard or attempt == max_stage_a_attempts:
            break
        turn = await step(f"{prefix}/revise_{attempt}", lambda: checks.revise(turn, hard, attempt))

    # Stage B: semantic LLM checks, once, on the final version. Flags only; no return to Stage A.
    soft = await _stage_b(step, f"{prefix}/stage_b", checks, turn, claims)
    log.append({"stage": "B", "findings": [f.to_dict() for f in soft]})

    status: Status = ("FLAGGED_BOTH" if hard and soft else "FLAGGED_HARD" if hard
                      else "FLAGGED_SOFT" if soft else "PASSED")
    return GateResult(turn, claims, status, hard + soft, attempt, log)
