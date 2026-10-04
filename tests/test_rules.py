"""Rule engine edge cases (CLAUDE.md §10 step N). Real-case fixtures are added once public cases exist."""
import datetime as dt

import pytest

from lexarena.rules import (Acknowledgment, Interval, class_creditor_threshold, dispute_ordering, limitation,
                            minimum_default, sec9_filing_window, sec10a_bar, sec61_appeal, sec62_appeal)
from lexarena.rules.dates import add_years
from lexarena.rules.smt import DateRange, limitation_modal

D = dt.date
COVID_SPAN = (D(2022, 2, 28) - D(2020, 3, 15)).days + 1


# ---- dates ----

def test_add_years_leap_day():
    assert add_years(D(2016, 2, 29), 3) == D(2019, 2, 28)
    assert add_years(D(2016, 2, 29), 4) == D(2020, 2, 29)


# ---- Article 137 + s.18 / s.19 / s.14 / s.4 ----

def test_three_years_same_calendar_date():
    r = limitation(D(2015, 12, 31), D(2018, 12, 31), covid=False)
    assert r.value == D(2018, 12, 31) and r.status == "WITHIN_LIMITATION"
    r = limitation(D(2015, 12, 31), D(2019, 1, 1), covid=False)
    assert r.status == "BARRED" and r.details["delay_days"] == 1
    assert any("s.5" in q for q in r.for_bench)


def test_acknowledgment_before_expiry_starts_fresh_period():
    r = limitation(D(2015, 12, 31), D(2020, 1, 10), [Acknowledgment(D(2018, 9, 5))], covid=False)
    assert r.value == D(2021, 9, 5) and r.status == "WITHIN_LIMITATION"


def test_acknowledgment_one_day_after_expiry_does_not_revive():
    r = limitation(D(2015, 12, 31), D(2020, 1, 10), [Acknowledgment(D(2019, 1, 1))], covid=False)
    assert r.value == D(2018, 12, 31) and r.status == "BARRED"


def test_acknowledgment_on_last_day_counts():
    r = limitation(D(2015, 12, 31), None, [Acknowledgment(D(2018, 12, 31))], covid=False)
    assert r.value == D(2021, 12, 31)


def test_chained_acknowledgments():
    acks = [Acknowledgment(D(2021, 5, 1)), Acknowledgment(D(2018, 6, 1))]   # order given does not matter
    r = limitation(D(2015, 12, 31), None, acks, covid=False)
    assert r.value == D(2024, 5, 1) and len(r.details["acknowledgments_used"]) == 2


def test_part_payment_needs_writing():
    r = limitation(D(2015, 12, 31), None, [Acknowledgment(D(2018, 6, 1), "PART_PAYMENT", in_writing=False)], covid=False)
    assert r.value == D(2018, 12, 31)


def test_s14_exclusion_counts_both_days():
    r = limitation(D(2015, 12, 31), None, s14_exclusions=(Interval(D(2017, 1, 1), D(2017, 1, 10)),), covid=False)
    assert r.value == D(2019, 1, 10)
    assert any("bona fide" in q for q in r.for_bench)


def test_closed_last_day_moves_to_next_open_day():
    r = limitation(D(2015, 12, 31), D(2019, 1, 1), covid=False, closed_days=frozenset({D(2018, 12, 31)}))
    assert r.value == D(2019, 1, 1) and r.status == "WITHIN_LIMITATION"


# ---- Supreme Court COVID order ----

def test_covid_exclusion_extends_running_period():
    r = limitation(D(2015, 12, 31), None, [Acknowledgment(D(2018, 9, 5))], covid=True)
    assert r.value == D(2021, 9, 5) + dt.timedelta(days=COVID_SPAN)


def test_covid_floor_when_period_expired_inside_window():
    r = limitation(D(2017, 3, 20), None, covid=True)      # nominal expiry 20.03.2020, inside the window
    assert D(2020, 3, 20) + dt.timedelta(days=COVID_SPAN) < D(2022, 5, 30)
    assert r.value == D(2022, 5, 30)


def test_covid_longer_balance_beats_floor():
    r = limitation(D(2019, 1, 1), None, covid=True)       # nominal expiry 01.01.2022, inside the window
    assert r.value == D(2022, 1, 1) + dt.timedelta(days=COVID_SPAN)


def test_default_inside_covid_window_runs_from_its_end():
    assert limitation(D(2020, 6, 1), None, covid=True).value == D(2025, 2, 28)


def test_no_covid_effect_before_window():
    assert limitation(D(2015, 1, 1), None, covid=True).value == D(2018, 1, 1)


# ---- s.4 threshold, class creditors ----

@pytest.mark.parametrize("filed, threshold", [(D(2020, 3, 23), 1_00_000), (D(2020, 3, 24), 1_00_00_000)])
def test_threshold_by_filing_date(filed, threshold):
    assert minimum_default(filed).value == threshold


def test_threshold_applies_to_amount_in_default():
    assert minimum_default(D(2020, 4, 1), 50_00_000).status == "NOT_MET"
    assert minimum_default(D(2019, 4, 1), 2_00_000).status == "MET"


def test_class_creditor_proviso():
    assert class_creditor_threshold(D(2020, 1, 1), 50, 500).status == "MET"          # 10% of 500 = 50
    assert class_creditor_threshold(D(2020, 1, 1), 99, 5000).status == "NOT_MET"     # min(100, 500) = 100
    assert class_creditor_threshold(D(2019, 12, 27), 1, 5000).status == "NOT_APPLICABLE"


# ---- s.10A ----

@pytest.mark.parametrize("default, status", [
    (D(2020, 3, 24), "NOT_BARRED"), (D(2020, 3, 25), "BARRED"), (D(2021, 3, 24), "BARRED"), (D(2021, 3, 25), "NOT_BARRED")])
def test_sec10a_boundaries(default, status):
    assert sec10a_bar([default]).status == status


def test_sec10a_mixed_defaults():
    assert sec10a_bar([D(2020, 1, 1), D(2020, 6, 1)]).status == "PARTLY_BARRED"


# ---- s.8 / s.9 ----

def test_sec9_day_10_vs_day_11():
    assert sec9_filing_window(D(2020, 1, 1), D(2020, 1, 11)).status == "PREMATURE"
    assert sec9_filing_window(D(2020, 1, 1), D(2020, 1, 12)).status == "FILED_AFTER_PERIOD"


def test_dispute_order_is_only_a_prefilter():
    r = dispute_ordering(D(2019, 12, 1), D(2020, 1, 1))
    assert r.status == "BEFORE_NOTICE" and any("Mobilox" in q for q in r.for_bench)
    assert dispute_ordering(D(2020, 1, 5), D(2020, 1, 1)).status == "AFTER_NOTICE"


# ---- s.61(2) / s.62 ----

@pytest.mark.parametrize("filed, status", [
    (D(2024, 1, 31), "WITHIN_PERIOD"), (D(2024, 2, 15), "CONDONABLE"), (D(2024, 2, 16), "BEYOND_CONDONABLE_LIMIT")])
def test_sec61_30_plus_15(filed, status):
    assert sec61_appeal(D(2024, 1, 1), filed).status == status


def test_sec61_certified_copy_exclusion_only_if_applied_in_time():
    r = sec61_appeal(D(2024, 1, 1), D(2024, 2, 15), certified_copy_applied=D(2024, 1, 5), certified_copy_ready=D(2024, 1, 20))
    assert r.details["excluded_days"] == 15 and r.status == "WITHIN_PERIOD"
    late = sec61_appeal(D(2024, 1, 1), D(2024, 2, 15), certified_copy_applied=D(2024, 2, 5), certified_copy_ready=D(2024, 2, 10))
    assert late.details["excluded_days"] == 0 and late.status == "CONDONABLE"


def test_sec62_45_plus_15():
    r = sec62_appeal(D(2024, 1, 1))
    assert r.details["limitation_end"] == D(2024, 2, 15) and r.details["condonable_until"] == D(2024, 3, 1)


# ---- Z3 over uncertain facts ----

DEFAULT = DateRange.exact(D(2015, 12, 31))
FILING = DateRange.exact(D(2020, 1, 10))


def test_smt_possibly_with_fy_acknowledgment():
    r = limitation_modal(DEFAULT, FILING, [DateRange(D(2018, 4, 1), D(2019, 3, 31))], covid=False)
    assert r.status == "POSSIBLY"
    assert r.details["witness_within"]["acknowledgments"][0] <= D(2018, 12, 31)
    assert r.details["witness_barred"]["acknowledgments"][0] > D(2018, 12, 31)


def test_smt_always_when_every_acknowledgment_is_in_time():
    assert limitation_modal(DEFAULT, FILING, [DateRange(D(2018, 4, 1), D(2018, 12, 31))], covid=False).status == "ALWAYS"


def test_smt_never_without_acknowledgment():
    assert limitation_modal(DEFAULT, FILING, [], covid=False).status == "NEVER"


def test_smt_uncertain_filing_date():
    r = limitation_modal(DEFAULT, DateRange(D(2018, 12, 1), D(2019, 1, 31)), [], covid=False)
    assert r.status == "POSSIBLY"


@pytest.mark.parametrize("ack, filing", [(D(2018, 9, 5), D(2020, 1, 10)), (D(2019, 1, 1), D(2020, 1, 10)),
                                         (D(2017, 3, 1), D(2023, 1, 1))])
def test_smt_agrees_with_plain_rule_on_exact_facts(ack, filing):
    plain = limitation(D(2015, 12, 31), filing, [Acknowledgment(ack)], covid=True)
    modal = limitation_modal(DEFAULT, DateRange.exact(filing), [DateRange.exact(ack)], covid=True)
    assert (plain.status == "WITHIN_LIMITATION") == (modal.status == "ALWAYS")
    assert (plain.status == "BARRED") == (modal.status == "NEVER")
