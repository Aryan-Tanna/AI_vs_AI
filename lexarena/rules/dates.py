"""Calendar arithmetic under the Limitation Act: periods in years follow the British calendar (s.25), and the
day from which a period runs is excluded (s.12(1)). So a 3-year period triggered on D ends on the same
calendar date three years later.
"""
import datetime as dt


def add_years(d: dt.date, years: int) -> dt.date:
    """Same calendar date `years` later; 29 February maps to 28 February in a non-leap year. VERIFY convention."""
    try:
        return d.replace(year=d.year + years)
    except ValueError:
        return dt.date(d.year + years, 2, 28)


def add_days(d: dt.date, days: int) -> dt.date:
    return d + dt.timedelta(days=days)


def inclusive_days(start: dt.date, end: dt.date) -> int:
    """Days in [start, end], both counted (s.14 Explanation (a): first and last day of the proceeding count)."""
    return (end - start).days + 1


def next_open_day(d: dt.date, closed: frozenset[dt.date]) -> dt.date:
    """s.4: if the period ends on a day the court is closed, file on the day it reopens."""
    while d in closed:
        d = add_days(d, 1)
    return d


def fmt(d: dt.date | None) -> str:
    return d.strftime("%d.%m.%Y") if d else "unknown"
