"""Limitation over uncertain facts with Z3 (CLAUDE.md §8.3, build step O).

When a date is known only to a range (an OTS letter "sometime in FY 2018-19", a filing date given as a month),
plain arithmetic cannot say whether the application was in time. Encode each uncertain date as a bounded
integer, encode the period-end function as a lookup table computed by `period_end` (so calendar years,
s.14 exclusions and the COVID order are exactly the same as in `limitation`), and ask:

  ∃ assignment: within limitation?   and   ∃ assignment: barred?

  both  -> POSSIBLY  (with a witness for each side)
  only within -> ALWAYS     only barred -> NEVER

Acknowledgments are assumed to be valid in form (signed writing); whether they are acknowledgments in law is
for the bench. They are taken in the order given (each no earlier than the previous one).
"""
import datetime as dt
from dataclasses import dataclass

import z3

from lexarena.rules.dates import fmt
from lexarena.rules.limitation import Interval, period_end
from lexarena.rules.result import RuleResult


@dataclass(frozen=True)
class DateRange:
    lo: dt.date
    hi: dt.date
    label: str = ""

    @classmethod
    def exact(cls, d: dt.date, label: str = "") -> "DateRange":
        return cls(d, d, label)

    def __post_init__(self):
        if self.hi < self.lo:
            raise ValueError(f"{self.label or 'range'}: hi before lo")


def _days(r: DateRange) -> range:
    return range(r.lo.toordinal(), r.hi.toordinal() + 1)


def limitation_modal(default: DateRange, filing: DateRange, acknowledgments: list[DateRange] = (),
                     s14_exclusions: tuple[Interval, ...] = (), years: int = 3, covid: bool = True) -> RuleResult:
    acks = list(acknowledgments)
    table = {o: period_end(dt.date.fromordinal(o), years, tuple(s14_exclusions), covid).toordinal()
             for r in [default, *acks] for o in _days(r)}

    E = z3.Function("period_end", z3.IntSort(), z3.IntSort())
    s = z3.Solver()
    for o, e in table.items():
        s.add(E(o) == e)

    def bounded(name: str, r: DateRange) -> z3.ArithRef:
        v = z3.Int(name)
        s.add(v >= r.lo.toordinal(), v <= r.hi.toordinal())
        return v

    d = bounded("default", default)
    f = bounded("filing", filing)
    a_vars = [bounded(f"ack_{i}", r) for i, r in enumerate(acks)]
    for prev, nxt in zip(a_vars, a_vars[1:]):
        s.add(prev <= nxt)

    trigger, expiry = d, E(d)
    for a in a_vars:
        valid = z3.And(a > trigger, a <= expiry)        # s.18: after the trigger, before the period expires
        trigger, expiry = z3.If(valid, a, trigger), z3.If(valid, E(a), expiry)
    within = f <= expiry

    def witness(goal) -> dict | None:
        s.push()
        s.add(goal)
        out = None
        if s.check() == z3.sat:
            m = s.model()
            def val(v):
                return dt.date.fromordinal(m.eval(v, model_completion=True).as_long())
            out = {"default": val(d), "filing": val(f), "acknowledgments": [val(a) for a in a_vars],
                   "expiry": val(expiry)}
        s.pop()
        return out

    w_in, w_out = witness(within), witness(z3.Not(within))
    status = "POSSIBLY" if (w_in and w_out) else "ALWAYS" if w_in else "NEVER"
    res = RuleResult(rule="LIMITATION_ART137_UNCERTAIN", status=status, value=status,
                     details={"witness_within": w_in, "witness_barred": w_out},
                     provisions=["LIMITATION_ACT_1963_ART_137", "LIMITATION_ACT_1963_SEC_18", "IBC_2016_SEC_238A"])
    res.steps.append(f"default in {fmt(default.lo)}-{fmt(default.hi)}, filing in {fmt(filing.lo)}-{fmt(filing.hi)}, "
                     + (", ".join(f"acknowledgment in {fmt(r.lo)}-{fmt(r.hi)}" for r in acks) or "no acknowledgments"))
    if w_in:
        res.steps.append("within limitation if, e.g., " + _describe(w_in))
    if w_out:
        res.steps.append("barred if, e.g., " + _describe(w_out))
    res.steps.append(f"result: {status}")
    if status == "POSSIBLY":
        res.for_bench.append("The outcome on limitation depends on facts the record leaves uncertain (see witnesses).")
    return res


def _describe(w: dict) -> str:
    acks = ", ".join(fmt(a) for a in w["acknowledgments"])
    return (f"default {fmt(w['default'])}" + (f", acknowledgments {acks}" if acks else "")
            + f", expiry {fmt(w['expiry'])}, filing {fmt(w['filing'])}")
