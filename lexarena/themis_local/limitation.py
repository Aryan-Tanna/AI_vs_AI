"""The limitation date chain (BUILD_PLAN Step 7; SPEC D3; D-063).

Shape only, from SPEC D3; every number and date is an approved overlay value:
- the period runs in calendar years from the date of default (a 29 February start ends on 28 February);
- an acknowledgment made on or before the current expiry starts a fresh period from its date; a later one does not;
- if an excluded window is approved and the period was running during it, the balance left when the window opened
  runs again from the day after the window closes, but never less than the approved minimum balance.

An acknowledgment made inside the excluded window is not computed (SPEC D3 caution): the result says
`needs_review`, and the audit leaves it to layer 2. With no approved period there is no rule, and nothing is checked.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from lexarena.schemas.overlay import DateRange
from lexarena.storage.temporal import AppliedOverlay


@dataclass(frozen=True)
class LimitationRule:
    period_years: int
    excluded: DateRange | None
    minimum_balance_days: int | None


@dataclass(frozen=True)
class LimitationResult:
    expiry: date
    needs_review: bool = False


def _add_years(d: date, years: int) -> date:
    try:
        return d.replace(year=d.year + years)
    except ValueError:  # 29 February in a non-leap year
        return d.replace(year=d.year + years, day=d.day - 1)


def limitation_expiry(default: date, acknowledgments: list[date], rule: LimitationRule) -> LimitationResult:
    excluded = rule.excluded
    if excluded and any(excluded.from_ <= ack <= excluded.to for ack in acknowledgments):
        return LimitationResult(_add_years(default, rule.period_years), needs_review=True)
    expiry = _add_years(default, rule.period_years)
    for ack in sorted(acknowledgments):
        if ack <= expiry:
            expiry = max(expiry, _add_years(ack, rule.period_years))
    if excluded and default <= excluded.to and expiry >= excluded.from_:
        running_from = max(default, excluded.from_)
        balance = (expiry - running_from).days
        resume = excluded.to + timedelta(days=1)
        expiry = resume + timedelta(days=max(balance, rule.minimum_balance_days or 0))
    return LimitationResult(expiry)


def rule_from_overlays(
    applied: list[AppliedOverlay], *, period: str, excluded: str, minimum: str
) -> LimitationRule | None:
    """Assemble the rule from the overlay values that apply on the case dates; None without an approved period."""
    values = {a.parameter: a.value for a in applied}
    years = values.get(period)
    if not isinstance(years, int) or isinstance(years, bool):
        return None
    window = values.get(excluded)
    floor = values.get(minimum)
    return LimitationRule(
        period_years=years,
        excluded=window if isinstance(window, DateRange) else None,
        minimum_balance_days=floor if isinstance(floor, int) and not isinstance(floor, bool) else None,
    )
