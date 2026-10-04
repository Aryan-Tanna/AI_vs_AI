"""IBC s.10A (CLAUDE.md §5.3): no s.7/9/10 application for a default on or after 25.03.2020 for one year
(to 24.03.2021); the proviso bars filing for such defaults at any time. Keyed on the date of default."""
import datetime as dt
from typing import Literal

from lexarena.rules import constants as C
from lexarena.rules.dates import fmt
from lexarena.rules.result import RuleResult


def sec10a_bar(default_dates: list[dt.date], application: Literal["SEC7", "SEC9", "SEC10"] = "SEC7") -> RuleResult:
    barred = [d for d in default_dates if C.SEC10A_START <= d <= C.SEC10A_END]
    clear = [d for d in default_dates if d not in barred]
    res = RuleResult(rule="SEC10A_BAR", status="", provisions=["IBC_2016_SEC_10A"],
                     details={"application": application, "barred_defaults": barred, "other_defaults": clear},
                     verify=["Window end 24.03.2021 (six months extended to one year)"])
    for d in sorted(default_dates):
        inside = d in barred
        res.steps.append(f"default {fmt(d)}: {'inside' if inside else 'outside'} {fmt(C.SEC10A_START)}-{fmt(C.SEC10A_END)}")
    if not default_dates:
        res.status = "NO_DEFAULT_DATE"
    elif not barred:
        res.status = "NOT_BARRED"
    elif not clear:
        res.status = "BARRED"
    else:
        res.status = "PARTLY_BARRED"
        res.for_bench.append("Do the defaults outside the s.10A window independently meet the threshold and support the application?")
    return res
