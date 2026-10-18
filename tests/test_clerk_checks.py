"""Clerk verification checks (BUILD_PLAN Step 6; SPEC H5, I3-8; D-056). Deterministic. Placeholder content only."""

from __future__ import annotations

from datetime import date

import pytest

from lexarena.clerk.checks import (
    amounts_in,
    date_written_in,
    grounds_balance,
    leakage_problems,
    literal_problems,
    reasoning_overlap,
)
from tests.test_clerk_assemble import build, draft


@pytest.mark.parametrize(
    "text",
    ["on 10.06.2014", "on 10/06/2014", "on 10-06-2014", "on 10.6.2014", "on 10th June, 2014", "on June 10, 2014",
     "on 10 June 2014", "on 2014-06-10"],
)  # fmt: skip
def test_a_date_is_found_in_any_common_form(text: str) -> None:
    assert date_written_in(date(2014, 6, 10), text)


def test_a_different_date_is_not_found() -> None:
    assert not date_written_in(date(2014, 6, 10), "on 11.06.2014 and 10.07.2014")


@pytest.mark.parametrize(
    ("text", "value"),
    [
        ("Rs. 3,88,00,000 was due", 38_800_000),
        ("a sum of Rs.3.88 Crores", 38_800_000),
        ("Rs 50 lakhs", 5_000_000),
        ("INR 12,500", 12_500),
        ("₹ 1.5 crore", 15_000_000),
        ("Rs. 2,35,47,382/-", 23_547_382),
    ],
)
def test_amounts_are_read_with_lakh_and_crore(text: str, value: int) -> None:
    assert value in amounts_in(text)


def test_literal_check_blocks_a_date_or_amount_missing_from_its_sources() -> None:
    view = build(draft()).view
    sources = {"P1": "default on 03.02.2001 for Rs. 100", "P2": "", "P4.S1": ""}
    assert literal_problems(view, sources) == []
    assert any("2001-02-03" in p for p in literal_problems(view, {**sources, "P1": "default for Rs. 100"}))
    assert any("AM1" in p for p in literal_problems(view, {**sources, "P1": "default on 03.02.2001"}))


def test_reasoning_copied_into_the_view_is_found_but_shared_boilerplate_is_not() -> None:
    reasoning = ["we hold that the proposal of the debtor can never extend the period of limitation at all"]
    visible = ["the application under section seven of the code was filed by the creditor on that day"]
    copied = "the proposal of the debtor can never extend the period of limitation"
    shared = "the application under section seven of the code was filed by the creditor"
    assert reasoning_overlap(copied, reasoning, visible, n=6)
    assert not reasoning_overlap(shared, reasoning + visible, visible, n=6)


def test_leakage_problems_cover_case_number_bench_date_and_issue_words() -> None:
    view = build(draft()).view
    clean = leakage_problems(
        view,
        case_number="<appeal no 9 of 2001>",
        bench=["Justice Qorvel Tamsin"],
        decision_date=date(2002, 1, 1),
        entities=[],
        authority_names=[],
        reasoning=[],
        visible=[],
        cfg_markers=["we are of the view"],
        evaluative_words=["erred"],
        generic_words=["justice"],
        ngram=6,
    )
    assert clean == []
    view.factual_background += " See <appeal no 9 of 2001>; Qorvel Tamsin; dated 01.01.2002."
    view.framed_issues[0].question = "Whether the forum erred"
    found = leakage_problems(
        view,
        case_number="<appeal no 9 of 2001>",
        bench=["Justice Qorvel Tamsin"],
        decision_date=date(2002, 1, 1),
        entities=[],
        authority_names=[],
        reasoning=[],
        visible=[],
        cfg_markers=["we are of the view"],
        evaluative_words=["erred"],
        generic_words=["justice"],
        ngram=6,
    )
    text = " | ".join(found)
    assert "case number" in text and "bench" in text and "decision date" in text and "erred" in text


def test_unbalanced_opening_grounds_are_flagged() -> None:
    view = build(draft()).view
    assert grounds_balance(view, max_ratio=3.0) is not None  # one ground for the petitioner, none for the respondent


@pytest.mark.parametrize(
    "text",
    ["the order in CP(IB) No. 177/NCLT/AHM/2020", "in Company Petition No.42 of 2019", "I.A. Nos. 12 and 14 of 2020"],
)
def test_any_registration_number_in_the_agent_view_is_refused(text: str) -> None:
    """The extractor is told never to include a case or appeal number (agent_view prompt); the lower forum's number
    slipped through on DEV_0008 because only the appeal's own number was searched (D-124)."""
    view = build(draft()).view
    view.factual_background += f" {text}."
    found = leakage_problems(
        view,
        case_number="",
        bench=[],
        decision_date=date(2002, 1, 1),
        entities=[],
        authority_names=[],
        reasoning=[],
        visible=[],
        cfg_markers=[],
        evaluative_words=[],
        generic_words=[],
        ngram=6,
    )
    assert any("registration number" in p for p in found)


@pytest.mark.parametrize(
    "text", ["notices went to a.b.shah@examplewire.com", "see www.examplewire.co.in", "at examplewire.com"]
)
def test_an_email_address_or_web_domain_in_the_agent_view_is_refused(text: str) -> None:
    """DEV_0008 F7 quoted two directors' e-mail addresses, carrying a real name and the company's name in lower case,
    which the name check (capitalised words) cannot see (D-128)."""
    view = build(draft()).view
    view.factual_background += f" {text}."
    found = leakage_problems(
        view,
        case_number="",
        bench=[],
        decision_date=date(2002, 1, 1),
        entities=[],
        authority_names=[],
        reasoning=[],
        visible=[],
        cfg_markers=[],
        evaluative_words=[],
        generic_words=[],
        ngram=6,
    )
    assert any("e-mail address or web domain" in p for p in found)


def test_section_numbers_and_abbreviations_are_not_web_domains() -> None:
    view = build(draft()).view
    view.factual_background += " Under Section 5.8 and Reg. 21, the I.U. record (e.g. p.74) and Rs.26.49 crore."
    found = leakage_problems(
        view,
        case_number="",
        bench=[],
        decision_date=date(2002, 1, 1),
        entities=[],
        authority_names=[],
        reasoning=[],
        visible=[],
        cfg_markers=[],
        evaluative_words=[],
        generic_words=[],
        ngram=6,
    )
    assert not any("web domain" in p for p in found)


def test_party_designations_sections_and_figures_are_not_registration_numbers() -> None:
    view = build(draft()).view
    view.factual_background += " Respondent No. 1 sent notice under Section 8 for Rs. 100 on 03.02.2001; No. 2 replied."
    found = leakage_problems(
        view,
        case_number="",
        bench=[],
        decision_date=date(2002, 1, 1),
        entities=[],
        authority_names=[],
        reasoning=[],
        visible=[],
        cfg_markers=[],
        evaluative_words=[],
        generic_words=[],
        ngram=6,
    )
    assert not any("registration number" in p for p in found)
