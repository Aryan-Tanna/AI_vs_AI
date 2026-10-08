"""What a judge reads (SPEC E1, E6; D-035, D-048): the allow-listed agent view, never agent names or hidden data."""

from __future__ import annotations

from lexarena.judges.packet import (
    cited_precedent_uids,
    fetch_precedents,
    record_ids,
    render_case,
    render_precedents,
    render_statutes,
    render_submissions,
    statutes_for_bench,
)
from tests import builders
from tests.judge_fixtures import HIDDEN_PRECEDENT_UID, PRECEDENT_UID, STATUTE, agent_view, fetcher, turns
from tests.test_layer1 import statute_view


def test_case_render_has_no_agent_names_dates_or_build_values() -> None:
    text = render_case(agent_view())
    for hidden in ("LEX_P", "LEX_D", "simulation_date", "<build>", builders.case_doc("X")["split"]):
        assert hidden not in text
    assert "<pseudonym A>: FINANCIAL_CREDITOR, APPELLANT; Petitioner's counsel" in text
    assert "<pseudonym B>: CORPORATE_DEBTOR, RESPONDENT_1; Respondent's counsel" in text


def test_every_record_item_is_shown_with_its_id() -> None:
    case = agent_view()
    text = render_case(case)
    assert record_ids(case) == {"F1", "C1", "EX-1", "AM1"}
    assert all(f"[{i}]" in text for i in record_ids(case))
    assert "nothing else is known about this document" in text


def test_presentation_order_swaps_the_blocks_and_keeps_turn_numbers() -> None:
    case, ts = agent_view(), turns()
    first = render_submissions(case, ts, "PETITIONER_FIRST")
    second = render_submissions(case, ts, "RESPONDENT_FIRST")
    assert first.index("PETITIONER'S COUNSEL") < first.index("RESPONDENT'S COUNSEL")
    assert second.index("RESPONDENT'S COUNSEL") < second.index("PETITIONER'S COUNSEL")
    assert sorted(first.splitlines()) == sorted(second.splitlines())  # same content, only the order differs
    assert "Turn 1 (OPENING" in first and "Turn 2 (OPENING" in first


def test_only_flagged_hard_errors_are_shown() -> None:
    text = render_submissions(agent_view(), turns(flagged=True), "PETITIONER_FIRST")
    assert "VERIFIER FLAG ERR_FACT_NOT_IN_RECORD on C1, F1" in text


def test_precedents_come_only_through_the_fetch_tool_and_excluded_ones_drop_out() -> None:
    calls: list[str] = []
    uids = cited_precedent_uids(turns())
    assert uids == [PRECEDENT_UID, HIDDEN_PRECEDENT_UID]
    found = fetch_precedents(uids, fetcher(calls))
    assert list(found) == [PRECEDENT_UID]
    assert calls == [f"{PRECEDENT_UID}:ratio", f"{HIDDEN_PRECEDENT_UID}:ratio"]
    assert HIDDEN_PRECEDENT_UID not in render_precedents(found)


def test_statutes_for_bench_unites_invoked_issue_and_claimed_statutes() -> None:
    assert statutes_for_bench(agent_view(), turns()) == [STATUTE]


def test_stored_threshold_is_marked_unverified_without_a_dated_value() -> None:
    view = statute_view(STATUTE)
    raw = view.record.to_document()
    raw["diagnostic_checklist"]["financial_threshold"] = {"minimum_amount": 5, "currency": "INR"}
    undated = view.model_copy(update={"record": type(view.record).model_validate(raw)})
    assert "not verified for this case's dates" in render_statutes({STATUTE: undated})
    dated = statute_view(STATUTE, {"minimum_default_inr": 5})
    dated = dated.model_copy(update={"record": undated.record})
    text = render_statutes({STATUTE: dated})
    assert "minimum_default_inr = 5 (applies on this case's dates)" in text
    assert "not verified" not in text
