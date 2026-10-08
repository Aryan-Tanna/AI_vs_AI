"""THEMIS-LOCAL layer 1: audit one statute's extracted checklist (BUILD_PLAN Step 7; SPEC D1, D3, D8; D-062).

The argument's checklist for a statute is compared with the Law DB entry as it applies on the case date
(`StatuteView`) and with the record's amounts. It checks whether counsel stated the law and the record accurately,
never whether the case is winnable.

Hard errors, each a tracked Z3 assertion so the unsat core names the code:
- ERR_THRESHOLD_MISSTATED: the claimed minimum differs from the dated threshold;
- ERR_THRESHOLD_APPLICATION: "met" or "not met" contradicts the record amount the argument relies on;
- ERR_TIMELINE_MISSTATED: a claimed period differs from the law.

The threshold is checked only against an APPROVED overlay value that covers the case date (D-062). The Law DB stores
one figure, today's; a case filed before a notification changed it would otherwise be held to the wrong number, and
an honest argument rejected. Without a dated value the claim becomes THRESHOLD_NOT_VERIFIABLE for layer 2. Timelines
use the dated overlay value when one applies, are left unchecked when one exists but could not be dated, and otherwise
use the Law DB value.

Everything uncertain is a warning or UNMAPPED and is never rejected (SPEC D1 point 4).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from fractions import Fraction

import z3  # type: ignore[import-untyped]

from lexarena.schemas.case import Amount
from lexarena.schemas.config import ThemisLocalConfig
from lexarena.schemas.law import LIST_FIELDS
from lexarena.schemas.transcript import ClaimedItem, ExtractedChecklist, ThemisWarning
from lexarena.storage.temporal import StatuteView

UNMAPPED = "UNMAPPED"
THRESHOLD_NOT_VERIFIABLE = "THRESHOLD_NOT_VERIFIABLE"
TIMELINE_KEYS = ("adjudication_window_days", "rectification_window_days")


@dataclass
class HardError:
    """A provable misstatement, with what the retry feedback needs (SPEC D7)."""

    code: str
    statute_id: str
    detail: str
    record_ids: list[str] = field(default_factory=list)


@dataclass
class StatuteAudit:
    statute_id: str
    hard_errors: list[HardError] = field(default_factory=list)
    warnings: list[ThemisWarning] = field(default_factory=list)


class _Checks:
    """Equalities the argument asserts, each tracked under its error code."""

    def __init__(self) -> None:
        self._pending: list[tuple[str, Fraction, Fraction, HardError]] = []

    def equal(self, code: str, claimed: float, actual: float, error: HardError) -> None:
        self._pending.append((code, Fraction(claimed), Fraction(actual), error))

    def failures(self) -> list[HardError]:
        failed: list[HardError] = []
        for code, claimed, actual, error in self._pending:
            solver = z3.Solver()
            solver.set(unsat_core=True)
            solver.assert_and_track(z3.RealVal(claimed) == z3.RealVal(actual), z3.Bool(code))
            if solver.check() == z3.unsat:
                failed.append(error)
        return failed


def _numeric(value: object) -> float | None:
    return value if isinstance(value, int | float) and not isinstance(value, bool) else None


def _unmapped(field_name: str, detail: str, quote: str | None = None) -> ThemisWarning:
    return ThemisWarning(code=UNMAPPED, field=field_name, detail=detail, quote=quote)


def _audit_threshold(
    view: StatuteView,
    claim: ExtractedChecklist,
    amounts: dict[str, Amount],
    cfg: ThemisLocalConfig,
    checks: _Checks,
    out: StatuteAudit,
) -> None:
    claimed = claim.diagnostic_checklist.financial_threshold
    mentions_threshold = claimed.minimum_amount is not None or claim.asserts_threshold_met is not None
    if not mentions_threshold:
        return
    dated = {a.parameter: a.value for a in view.applied}
    law_min = _numeric(dated.get(cfg.threshold_overlay_parameter))
    if law_min is None:
        out.warnings.append(
            ThemisWarning(
                code=THRESHOLD_NOT_VERIFIABLE,
                field="financial_threshold",
                detail="no approved threshold covers the case date; left to layer 2",
            )
        )
        return
    if claimed.minimum_amount is not None:
        if claimed.currency not in (None, cfg.threshold_currency):
            out.warnings.append(_unmapped("financial_threshold", f"currency {claimed.currency!r} not comparable"))
        else:
            checks.equal(
                "ERR_THRESHOLD_MISSTATED",
                claimed.minimum_amount,
                law_min,
                HardError(
                    "ERR_THRESHOLD_MISSTATED", view.statute_id, f"stated {claimed.minimum_amount}; law {law_min}"
                ),
            )
    if claim.asserts_threshold_met is not None:
        amount = amounts.get(claim.threshold_amount_id or "")
        if amount is None:
            out.warnings.append(
                _unmapped("financial_threshold", f"threshold applied to unknown amount {claim.threshold_amount_id!r}")
            )
            return
        met = Fraction(amount.value_inr) >= Fraction(law_min)
        checks.equal(
            "ERR_THRESHOLD_APPLICATION",
            float(claim.asserts_threshold_met),
            float(met),
            HardError(
                "ERR_THRESHOLD_APPLICATION",
                view.statute_id,
                f"says the threshold is {'met' if claim.asserts_threshold_met else 'not met'}; "
                f"{amount.amount_id} is {amount.value_inr} against {law_min}",
                [amount.amount_id],
            ),
        )


def _audit_timelines(view: StatuteView, claim: ExtractedChecklist, checks: _Checks, out: StatuteAudit) -> None:
    dated = {a.parameter: a.value for a in view.applied}
    undated = {u.parameter for u in view.unresolved}
    for key in TIMELINE_KEYS:
        value = getattr(claim.procedural_timelines, key)
        if value is None:
            continue
        if key in dated:
            law_value = _numeric(dated[key])
        elif key in undated:
            out.warnings.append(_unmapped(key, "the dated value could not be resolved for this case"))
            continue
        else:
            law_value = getattr(view.record.procedural_timelines, key)
        if law_value is None:
            continue
        checks.equal(
            "ERR_TIMELINE_MISSTATED",
            value,
            law_value,
            HardError("ERR_TIMELINE_MISSTATED", view.statute_id, f"{key}: stated {value}; law {law_value}"),
        )


def _audit_items(view: StatuteView, claim: ExtractedChecklist, cfg: ThemisLocalConfig, out: StatuteAudit) -> None:
    for field_name in LIST_FIELDS:
        law_items: list[str] = getattr(view.record.diagnostic_checklist, field_name)
        claimed: list[ClaimedItem] = getattr(claim.diagnostic_checklist, field_name)
        for item in claimed:
            if item.confidence < cfg.extraction_min_confidence or not item.quote.strip():
                out.warnings.append(_unmapped(field_name, "low confidence or no quoted span", item.quote or None))
            elif item.law_index is None:
                out.warnings.append(
                    ThemisWarning(code="WARN_CONDITION_NOT_IN_STATUTE", field=field_name, quote=item.quote)
                )
            elif item.law_index >= len(law_items):
                out.warnings.append(_unmapped(field_name, f"no item {item.law_index} in the law", item.quote))
    if claim.stance == "ASSERT_CLAIM":
        required = range(len(view.record.diagnostic_checklist.mandatory_prerequisites))
        addressed = {
            i.law_index
            for i in claim.diagnostic_checklist.mandatory_prerequisites
            if i.law_index is not None and i.confidence >= cfg.extraction_min_confidence and i.quote.strip()
        }
        missing = [i for i in required if i not in addressed]
        if missing:
            out.warnings.append(
                ThemisWarning(
                    code="WARN_PREREQUISITE_UNADDRESSED", field="mandatory_prerequisites", law_indices=missing
                )
            )


def audit_statute(
    view: StatuteView, claim: ExtractedChecklist, amounts: dict[str, Amount], cfg: ThemisLocalConfig
) -> StatuteAudit:
    if claim.statute_id != view.statute_id:
        raise ValueError(f"checklist for {claim.statute_id} audited against {view.statute_id}")
    out = StatuteAudit(view.statute_id)
    checks = _Checks()
    _audit_threshold(view, claim, amounts, cfg, checks, out)
    _audit_timelines(view, claim, checks, out)
    _audit_items(view, claim, cfg, out)
    out.hard_errors = checks.failures()
    return out
