"""The limitation date chain (BUILD_PLAN Step 7; SPEC D3; D-063).

Every period and window comes from approved overlay values passed in as a rule; the code holds only the chain's
shape (SPEC D3). Values below are placeholders chosen to exercise each branch, not the real law.
"""

from __future__ import annotations

from datetime import date, timedelta

from lexarena.schemas.overlay import DateRange
from lexarena.storage.temporal import AppliedOverlay
from lexarena.themis_local.limitation import LimitationRule, limitation_expiry, rule_from_overlays

RULE = LimitationRule(
    period_years=3,
    excluded=DateRange.model_validate({"from": date(2010, 3, 15), "to": date(2012, 2, 28)}),
    minimum_balance_days=90,
)
RESUME = date(2012, 2, 29)  # the day after the window closes (a leap year)
PLAIN = LimitationRule(period_years=3, excluded=None, minimum_balance_days=None)


def test_calendar_years_from_default() -> None:
    assert limitation_expiry(date(2001, 6, 1), [], PLAIN).expiry == date(2004, 6, 1)
    assert limitation_expiry(date(2000, 2, 29), [], PLAIN).expiry == date(2003, 2, 28)


def test_only_an_acknowledgment_before_expiry_restarts_the_period() -> None:
    assert limitation_expiry(date(2001, 6, 1), [date(2003, 1, 1)], PLAIN).expiry == date(2006, 1, 1)
    assert limitation_expiry(date(2001, 6, 1), [date(2005, 1, 1)], PLAIN).expiry == date(2004, 6, 1)  # too late
    chained = limitation_expiry(date(2001, 6, 1), [date(2003, 1, 1), date(2005, 6, 1)], PLAIN)
    assert chained.expiry == date(2008, 6, 1)


def test_an_expiry_inside_the_excluded_window_gets_at_least_the_minimum_balance() -> None:
    # default 2007-04-01 -> expiry 2010-04-01; 17 days left at the window's start, so the minimum applies
    result = limitation_expiry(date(2007, 4, 1), [], RULE)
    assert result.expiry == RESUME + timedelta(days=90)


def test_a_default_inside_the_window_runs_the_whole_period_from_the_resumption() -> None:
    result = limitation_expiry(date(2011, 1, 1), [], RULE)
    assert result.expiry == RESUME + (date(2014, 1, 1) - date(2011, 1, 1))


def test_a_default_after_the_window_is_unaffected() -> None:
    assert limitation_expiry(date(2013, 1, 1), [], RULE).expiry == date(2016, 1, 1)


def test_an_acknowledgment_inside_the_window_needs_review() -> None:
    assert limitation_expiry(date(2008, 6, 1), [date(2011, 1, 1)], RULE).needs_review


def test_the_rule_is_built_only_from_approved_overlay_values() -> None:
    names = {"period": "P", "excluded": "X", "minimum": "M"}
    period = AppliedOverlay(overlay_id="O1", parameter="P", value=3, keyed_on="DEFAULT")
    window = AppliedOverlay(overlay_id="O2", parameter="X", value=RULE.excluded, keyed_on="DEFAULT")
    minimum = AppliedOverlay(overlay_id="O3", parameter="M", value=90, keyed_on="DEFAULT")
    assert rule_from_overlays([period, window, minimum], **names) == RULE
    assert rule_from_overlays([period], **names) == PLAIN
    assert rule_from_overlays([window, minimum], **names) is None  # no approved period: nothing is checked
