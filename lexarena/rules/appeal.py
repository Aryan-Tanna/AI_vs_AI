"""Appeal limitation (CLAUDE.md §5.7).

s.61(2): 30 days from the order; up to 15 more days on sufficient cause; no power beyond 45 days. Time runs from
pronouncement where the party is present or aware (V. Nagarajan v. SKS Ispat), not from receipt of the copy.
s.62: appeal to the Supreme Court, 45 days + 15.
s.12(2) Limitation Act: time requisite to obtain a certified copy is excluded, only if it was applied for
within the limitation period.
"""
import datetime as dt

from lexarena.rules import constants as C
from lexarena.rules.dates import add_days, fmt
from lexarena.rules.result import RuleResult


def appeal_timeline(order_date: dt.date, filing_date: dt.date | None = None, *, base_days: int, extra_days: int,
                    provision: str, certified_copy_applied: dt.date | None = None,
                    certified_copy_ready: dt.date | None = None) -> RuleResult:
    res = RuleResult(rule=provision, status="", provisions=[provision, "LIMITATION_ACT_1963_SEC_12"])
    base_end = add_days(order_date, base_days)
    res.steps.append(f"order pronounced {fmt(order_date)}: {base_days} days end {fmt(base_end)} (order day excluded)")

    excluded = 0
    if certified_copy_applied and certified_copy_ready:
        if certified_copy_applied <= base_end:
            excluded = max(0, (certified_copy_ready - certified_copy_applied).days)
            res.steps.append(f"certified copy applied {fmt(certified_copy_applied)}, ready {fmt(certified_copy_ready)}: "
                             f"exclude {excluded} days (s.12(2))")
            res.verify.append("Counting of s.12(2) days (application day excluded, ready day included) and whether "
                              "the exclusion also extends the outer condonable limit")
        else:
            res.steps.append(f"certified copy applied {fmt(certified_copy_applied)}, after {fmt(base_end)}: no exclusion")
    base_end = add_days(base_end, excluded)
    outer_end = add_days(base_end, extra_days)
    res.value = base_end
    res.details = {"order_date": order_date, "limitation_end": base_end, "condonable_until": outer_end,
                   "excluded_days": excluded}
    res.steps.append(f"limitation ends {fmt(base_end)}; condonable until {fmt(outer_end)}")
    res.for_bench.append("Was the party present at, or aware of, the pronouncement (start date per V. Nagarajan)?")

    if filing_date is None:
        res.status = "DEADLINES_COMPUTED"
    elif filing_date <= base_end:
        res.status = "WITHIN_PERIOD"
    elif filing_date <= outer_end:
        res.status = "CONDONABLE"
        res.details["delay_days"] = (filing_date - base_end).days
        res.for_bench.append(f"Is there sufficient cause for the {res.details['delay_days']}-day delay?")
    else:
        res.status = "BEYOND_CONDONABLE_LIMIT"
        res.details["delay_days"] = (filing_date - base_end).days
        res.steps.append("no power to condone beyond the outer limit")
    if filing_date:
        res.steps.append(f"filed {fmt(filing_date)}: {res.status}")
    return res


def sec61_appeal(order_date: dt.date, filing_date: dt.date | None = None, **kw) -> RuleResult:
    return appeal_timeline(order_date, filing_date, base_days=C.SEC61_BASE_DAYS, extra_days=C.SEC61_EXTRA_DAYS,
                           provision="IBC_2016_SEC_61", **kw)


def sec62_appeal(order_date: dt.date, filing_date: dt.date | None = None, **kw) -> RuleResult:
    return appeal_timeline(order_date, filing_date, base_days=C.SEC62_BASE_DAYS, extra_days=C.SEC62_EXTRA_DAYS,
                           provision="IBC_2016_SEC_62", **kw)
