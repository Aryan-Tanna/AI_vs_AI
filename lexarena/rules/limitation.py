"""Limitation for s.7 / s.9 applications (CLAUDE.md §5.2).

- Article 137: 3 years from the date of default (B.K. Educational Services v. Parag Gupta); s.238A IBC applies
  the Limitation Act.
- s.12(1) / s.25: exclude the trigger day; count in calendar years.
- s.18 acknowledgment and s.19 part-payment: valid only if made before the period expires; a fresh period runs
  from its date. Chainable. Part-payment also needs a written acknowledgment of the payment.
- s.14: time spent bona fide in a wrong forum is excluded (both end days counted). Whether the proceeding was
  bona fide and with due diligence is for the bench; the caller decides which intervals to pass.
- Supreme Court suo motu order: 15.03.2020-28.02.2022 excluded; if the period would have expired inside that
  window, at least until the floor date (90 days from 01.03.2022).
- s.5 condonation can apply to s.7 applications (Sesh Nath Singh); whether to condone is for the bench.
"""
import datetime as dt
from dataclasses import dataclass
from typing import Literal

from lexarena.rules import constants as C
from lexarena.rules.dates import add_years, fmt, inclusive_days, next_open_day
from lexarena.rules.result import RuleResult


@dataclass(frozen=True)
class Interval:
    start: dt.date
    end: dt.date
    reason: str = "s.14 proceeding"


@dataclass(frozen=True)
class Acknowledgment:
    date: dt.date
    kind: Literal["ACKNOWLEDGMENT", "PART_PAYMENT"] = "ACKNOWLEDGMENT"
    in_writing: bool = True                 # s.18 needs a signed writing; s.19 needs the payment acknowledged in writing
    label: str = ""


COVID = Interval(C.COVID_EXCLUDED_START, C.COVID_EXCLUDED_END, "Supreme Court suo motu exclusion")


def period_end(trigger: dt.date, years: int = 3, exclusions: tuple[Interval, ...] = (), covid: bool = True,
               steps: list[str] | None = None) -> dt.date:
    """Last day of a `years`-year period triggered on `trigger`, after exclusions (s.4 not applied here)."""
    log = steps if steps is not None else []
    start = trigger
    intervals = sorted(list(exclusions) + ([COVID] if covid else []), key=lambda iv: iv.start)

    for iv in intervals:                                   # trigger inside an excluded interval: time starts after it
        if iv.start <= start <= iv.end:
            log.append(f"trigger {fmt(start)} falls inside {iv.reason} ({fmt(iv.start)}-{fmt(iv.end)}); time runs from {fmt(iv.end)}")
            start = iv.end
    end = add_years(start, years)
    log.append(f"{years} years from {fmt(start)} (trigger day excluded) ends {fmt(end)}")

    for iv in intervals:
        if start < iv.start <= end:
            extra = inclusive_days(iv.start, iv.end)
            end = end + dt.timedelta(days=extra)
            log.append(f"exclude {iv.reason} {fmt(iv.start)}-{fmt(iv.end)} (+{extra} days) -> {fmt(end)}")

    if covid:
        nominal = period_end(trigger, years, exclusions, covid=False, steps=[])
        if C.COVID_EXCLUDED_START <= nominal <= C.COVID_EXCLUDED_END and end < C.COVID_FLOOR_END:
            log.append(f"period would have expired {fmt(nominal)} inside the excluded window: floor {fmt(C.COVID_FLOOR_END)}")
            end = C.COVID_FLOOR_END
    return end


def limitation(default_date: dt.date, filing_date: dt.date | None = None,
               acknowledgments: tuple[Acknowledgment, ...] | list[Acknowledgment] = (),
               s14_exclusions: tuple[Interval, ...] = (), years: int = 3, covid: bool = True,
               closed_days: frozenset[dt.date] = frozenset()) -> RuleResult:
    steps: list[str] = []
    res = RuleResult(rule="LIMITATION_ART137", status="", provisions=[
        "LIMITATION_ACT_1963_ART_137", "LIMITATION_ACT_1963_SEC_12", "LIMITATION_ACT_1963_SEC_18",
        "LIMITATION_ACT_1963_SEC_19", "IBC_2016_SEC_238A"], steps=steps)
    s14 = tuple(s14_exclusions)
    if s14:
        res.provisions.append("LIMITATION_ACT_1963_SEC_14")
        res.for_bench.append("Were the excluded proceedings prosecuted bona fide and with due diligence in a forum without jurisdiction (s.14)?")

    trigger = default_date
    steps.append(f"default on {fmt(default_date)}")
    expiry = period_end(trigger, years, s14, covid, steps)
    used: list[dict] = []
    for ack in sorted(acknowledgments, key=lambda a: a.date):
        name = ack.label or f"{ack.kind.lower()} {fmt(ack.date)}"
        if not ack.in_writing:
            steps.append(f"{name}: ignored (s.18/s.19 need a writing signed by the party / acknowledging the payment)")
            continue
        if ack.date <= trigger:
            steps.append(f"{name}: on/before the current trigger {fmt(trigger)}; no fresh period")
            continue
        if ack.date > expiry:
            steps.append(f"{name}: after expiry on {fmt(expiry)}; cannot revive a barred claim")
            continue
        steps.append(f"{name}: before expiry {fmt(expiry)}; fresh period from {fmt(ack.date)}")
        trigger = ack.date
        expiry = period_end(trigger, years, s14, covid, steps)
        used.append({"date": ack.date, "kind": ack.kind})
    if acknowledgments:
        res.for_bench.append("Does each acknowledgment relied on amount to an acknowledgment of liability in law "
                             "(e.g. a balance sheet entry, Bishal Jaiswal) - a question of fact?")
        res.verify.append("Acknowledgment signed on the last day of the period is treated as 'before expiration'")

    last_day = next_open_day(expiry, closed_days)
    if last_day != expiry:
        steps.append(f"{fmt(expiry)} is a closed day: last day moves to {fmt(last_day)} (s.4)")
    res.value = last_day
    res.details = {"default_date": default_date, "final_trigger": trigger, "expiry": last_day,
                   "acknowledgments_used": used, "covid_applied": covid}

    if filing_date is None:
        res.status = "EXPIRY_COMPUTED"
    elif filing_date <= last_day:
        res.status = "WITHIN_LIMITATION"
        steps.append(f"filed {fmt(filing_date)} on/before {fmt(last_day)}: within limitation")
    else:
        res.status = "BARRED"
        delay = (filing_date - last_day).days
        res.details["delay_days"] = delay
        steps.append(f"filed {fmt(filing_date)}, {delay} day(s) after {fmt(last_day)}: barred unless delay condoned")
        res.for_bench.append("Is there sufficient cause to condone the delay under s.5 (applies to s.7, Sesh Nath Singh)?")
    if covid:
        res.verify.append(f"COVID floor date {fmt(C.COVID_FLOOR_END)} (90 days from 01.03.2022)")
    return res
