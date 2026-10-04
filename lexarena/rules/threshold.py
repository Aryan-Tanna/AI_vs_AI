"""IBC s.4 minimum default and the s.7 class-creditor proviso (CLAUDE.md §5.1)."""
import datetime as dt
import math

from lexarena.rules import constants as C
from lexarena.rules.dates import fmt
from lexarena.rules.result import RuleResult


def minimum_default(filing_date: dt.date, amount_in_default_inr: float | None = None) -> RuleResult:
    """Threshold in force on the filing date, applied to the amount *in default* (not the total claim).
    For s.7 the default may be to any financial creditor (Explanation to s.7(1))."""
    new = filing_date >= C.THRESHOLD_CHANGE_DATE
    threshold = C.THRESHOLD_NEW_INR if new else C.THRESHOLD_OLD_INR
    res = RuleResult(rule="MIN_DEFAULT_SEC4", status="", value=threshold, provisions=["IBC_2016_SEC_4"],
                     details={"filing_date": filing_date, "threshold_inr": threshold, "amount_in_default_inr": amount_in_default_inr},
                     verify=["Threshold change applies prospectively by filing date; boundary day 24.03.2020 counts as the new threshold"])
    res.steps.append(f"filed {fmt(filing_date)}: threshold ₹{threshold:,} "
                     f"({'notification of 24.03.2020' if new else 'original s.4'})")
    if amount_in_default_inr is None:
        res.status = "THRESHOLD_ONLY"
    else:
        res.status = "MET" if amount_in_default_inr >= threshold else "NOT_MET"
        res.steps.append(f"amount in default ₹{amount_in_default_inr:,.0f} {'≥' if res.status == 'MET' else '<'} ₹{threshold:,}")
    return res


def class_creditor_threshold(filing_date: dt.date, applicants: int, total_in_class: int) -> RuleResult:
    """Real-estate allottees and other class creditors: at least 100 of the class or 10% of it, whichever is less."""
    res = RuleResult(rule="SEC7_CLASS_CREDITOR_PROVISO", status="", provisions=["IBC_2016_SEC_7"],
                     details={"applicants": applicants, "total_in_class": total_in_class})
    if filing_date < C.CLASS_CREDITOR_FROM:
        res.status = "NOT_APPLICABLE"
        res.steps.append(f"filed {fmt(filing_date)}, before the proviso took effect on {fmt(C.CLASS_CREDITOR_FROM)}")
        res.verify.append("Treatment of applications pending on 28.12.2019 (Manish Kumar v. UoI)")
        return res
    required = min(C.CLASS_CREDITOR_MIN_COUNT, math.ceil(C.CLASS_CREDITOR_MIN_FRACTION * total_in_class))
    res.value = required
    res.status = "MET" if applicants >= required else "NOT_MET"
    res.steps.append(f"required min(100, 10% of {total_in_class}) = {required}; applicants {applicants}: {res.status}")
    res.verify.append("10% rounded up to a whole creditor")
    return res
