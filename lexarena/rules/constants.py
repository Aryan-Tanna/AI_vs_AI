"""Dates and amounts the rules depend on. Every value here is a legal fact: change it only with a source.

Items marked VERIFY must be checked against the Gazette / the Supreme Court order before results are
reported (CLAUDE.md §5).
"""
import datetime as dt

D = dt.date

# IBC s.4 minimum default (CLAUDE.md §5.1)
THRESHOLD_OLD_INR = 1_00_000            # ₹1 lakh
THRESHOLD_NEW_INR = 1_00_00_000         # ₹1 crore
THRESHOLD_CHANGE_DATE = D(2020, 3, 24)  # notification dated 24.03.2020; applies to applications filed on/after. VERIFY S.O. number and boundary day

# s.7 class-creditor / allottee provisos (2020 Amendment, w.e.f. 28.12.2019; upheld in Manish Kumar v. UoI)
CLASS_CREDITOR_FROM = D(2019, 12, 28)
CLASS_CREDITOR_MIN_COUNT = 100
CLASS_CREDITOR_MIN_FRACTION = 0.10

# IBC s.10A (CLAUDE.md §5.3)
SEC10A_START = D(2020, 3, 25)
SEC10A_END = D(2021, 3, 24)             # six months, extended to one year. VERIFY extension notifications

# Supreme Court suo motu limitation order (CLAUDE.md §5.2)
COVID_EXCLUDED_START = D(2020, 3, 15)
COVID_EXCLUDED_END = D(2022, 2, 28)
COVID_FLOOR_END = D(2022, 5, 30)        # "90 days from 01.03.2022". VERIFY last day (29.05 vs 30.05)

# Appeals (CLAUDE.md §5.7)
SEC61_BASE_DAYS, SEC61_EXTRA_DAYS = 30, 15
SEC62_BASE_DAYS, SEC62_EXTRA_DAYS = 45, 15
