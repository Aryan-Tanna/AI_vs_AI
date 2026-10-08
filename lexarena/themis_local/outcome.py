"""The SPEC D8 outcome policy and the retry loop (BUILD_PLAN Step 8; SPEC D6, D7, D8; D-075).

- Only the closed list of hard-error codes (`schemas/codes.py`) triggers a revision. Anything else is a warning.
- A draft with hard errors goes back to its lawyer with the exact codes, IDs and details (D7), up to
  `themis_local.retry_cap` times. If the last attempt still has hard errors it is published FLAGGED, and the opponent
  and the judges see each remaining code (`VisibleFlag`). Warnings stay private to the side's reflection.
- `s_local` is a score, never a gate (D6): `score_weights.rule` x the share of applicable checklist items the argument
  addresses + `score_weights.llm` x responsiveness (1 when there was nothing to respond to).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from lexarena.schemas.agent import LawyerDraft
from lexarena.schemas.codes import HARD_ERROR_CODES
from lexarena.schemas.config import ThemisLocalConfig
from lexarena.schemas.transcript import ThemisLocalResult, ThemisWarning, VisibleFlag
from lexarena.themis_local.layer2 import Problem
from lexarena.themis_local.verify import Verification


class UnknownHardErrorError(ValueError):
    """A check produced a code outside the closed SPEC D8 list; refused rather than allowed to reject."""


def feedback(problems: list[Problem]) -> str:
    """The retry message (SPEC D7): one line per problem with its code and the IDs involved."""
    lines = []
    for p in problems:
        ids = ", ".join([*p.claim_ids, *p.record_ids])
        lines.append(f"- {p.code}{f' [{ids}]' if ids else ''}: {p.detail}")
    return "\n".join(lines)


def s_local(v: Verification, cfg: ThemisLocalConfig) -> float:
    responsiveness = 1.0 if v.responsiveness is None else v.responsiveness
    return cfg.score_weights.rule * v.rule_coverage + cfg.score_weights.llm * responsiveness


@dataclass(frozen=True)
class VerifiedTurn:
    draft: LawyerDraft
    verification: Verification
    result: ThemisLocalResult
    flags: list[VisibleFlag]


def _codes(problems: list[Problem]) -> list[str]:
    unknown = sorted({p.code for p in problems} - HARD_ERROR_CODES)
    if unknown:
        raise UnknownHardErrorError(f"codes {unknown} are not SPEC D8 hard errors")
    return [p.code for p in problems]


def verify_with_retries(
    write: Callable[[str | None], LawyerDraft],
    check: Callable[[LawyerDraft], Verification],
    cfg: ThemisLocalConfig,
) -> VerifiedTurn:
    """`write(feedback)` asks the lawyer for a draft (None on the first attempt); `check` runs THEMIS on it."""
    errors_by_attempt: list[list[str]] = []
    note: str | None = None
    while True:
        draft = write(note)
        v = check(draft)
        errors_by_attempt.append(_codes(v.hard_errors))
        if not v.hard_errors or len(errors_by_attempt) > cfg.retry_cap:
            break
        note = feedback(v.hard_errors)
    warnings: list[ThemisWarning] = list(v.warnings)
    outcome = "FLAGGED" if v.hard_errors else "PASS_WITH_NOTES" if warnings else "PASS"
    result = ThemisLocalResult(
        outcome=outcome,
        attempts=len(errors_by_attempt),
        hard_errors_by_attempt=errors_by_attempt,
        warnings=warnings,
        s_local=s_local(v, cfg),
    )
    flags = [VisibleFlag(code=p.code, claim_ids=p.claim_ids, record_ids=p.record_ids) for p in v.hard_errors]
    return VerifiedTurn(draft=draft, verification=v, result=result, flags=flags)
