"""IBC s.8 / s.9 timing (CLAUDE.md §5.4).

s.8(2): the corporate debtor has 10 days from receipt of the demand notice to point out a dispute.
s.9(1): the application may be filed only after the expiry of 10 days from delivery, i.e. filing > delivery + 10.
Mobilox: the test is a plausible, pre-existing dispute; this module only checks date order.
"""
import datetime as dt

from lexarena.rules.dates import add_days, fmt
from lexarena.rules.result import RuleResult


def sec9_filing_window(delivery_date: dt.date, filing_date: dt.date | None = None) -> RuleResult:
    reply_deadline = add_days(delivery_date, 10)
    earliest = add_days(delivery_date, 11)
    res = RuleResult(rule="SEC9_NOTICE_PERIOD", status="", value=earliest, provisions=["IBC_2016_SEC_8", "IBC_2016_SEC_9"],
                     details={"delivery_date": delivery_date, "reply_deadline": reply_deadline, "earliest_filing": earliest})
    res.steps.append(f"notice delivered {fmt(delivery_date)}: 10-day period ends {fmt(reply_deadline)}; "
                     f"earliest filing {fmt(earliest)}")
    if filing_date is None:
        res.status = "WINDOW_COMPUTED"
    elif filing_date >= earliest:
        res.status = "FILED_AFTER_PERIOD"
    else:
        res.status = "PREMATURE"
        res.steps.append(f"filed {fmt(filing_date)}, before {fmt(earliest)}")
    return res


def dispute_ordering(dispute_date: dt.date | None, delivery_date: dt.date) -> RuleResult:
    res = RuleResult(rule="SEC9_DISPUTE_ORDER", status="", provisions=["IBC_2016_SEC_8", "IBC_2016_SEC_9"],
                     details={"dispute_date": dispute_date, "delivery_date": delivery_date})
    res.for_bench.append("Is the dispute plausible and not spurious, hypothetical or illusory (Mobilox)?")
    if dispute_date is None:
        res.status = "NO_DOCUMENTED_DISPUTE_DATE"
    elif dispute_date < delivery_date:
        res.status = "BEFORE_NOTICE"
    elif dispute_date == delivery_date:
        res.status = "SAME_DAY"
    else:
        res.status = "AFTER_NOTICE"
        res.for_bench.append("Does the later document evidence a dispute that existed before the notice?")
    res.steps.append(f"documented dispute {fmt(dispute_date)} vs notice delivered {fmt(delivery_date)}: {res.status}")
    return res
