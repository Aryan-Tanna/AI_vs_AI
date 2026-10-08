"""Assembling the agent view from the extractor's draft (BUILD_PLAN Step 6, D-056). Code sets what the model must
not decide and refuses what it cannot verify. Placeholder content only (non-negotiable 1)."""

from __future__ import annotations

from datetime import date
from typing import Any

from lexarena.clerk.assemble import build_agent_view
from lexarena.schemas.clerk import AgentViewDraft
from lexarena.schemas.statute_alias import StatuteAliasTable

VISIBLE = {"P1", "P2", "P4.S1"}
KNOWN = {"TEST_ACT_SEC_7", "TEST_ACT_SEC_9"}
LABELS = ["DEFAULT", "FILING", "DECISION"]
PRESUMPTIONS = ["<presumption>"]


def draft(**change: Any) -> AgentViewDraft:
    base: dict[str, Any] = {
        "proceeding_type": "APPEAL_UNDER_SEC_61",
        "statutes_invoked": ["TEST_ACT_SEC_7"],
        "key_dates": [{"label": "DEFAULT", "date": "2001-02-03", "fact_id": "F1"}],
        "parties": [
            {
                "party_id": "A1",
                "pseudonym": "Bank-K",
                "status": "FINANCIAL_CREDITOR",
                "simulation_side": "PETITIONER",
                "appeal_position": "APPELLANT",
                "substituted_from": None,
            },
            {
                "party_id": "R1",
                "pseudonym": "Company-B",
                "status": "CORPORATE_DEBTOR",
                "simulation_side": "RESPONDENT",
                "appeal_position": "RESPONDENT_1",
                "substituted_from": None,
            },
        ],
        "factual_background": "<background> [F1]",
        "record": {
            "stipulated_facts": [{"fact_id": "F1", "text": "<fact>", "source_paras": ["P1"]}],
            "contested_facts": [],
            "exhibits": [
                {
                    "exhibit_id": "EX-1",
                    "title": "<letter>",
                    "filed_by": "A1",
                    "known_contents": ["<content>"],
                    "contents_beyond_known": "UNKNOWN",
                    "authenticity": "PRESUMED",
                    "source_paras": ["P4.S1"],
                }
            ],
            "amounts": [
                {
                    "amount_id": "AM1",
                    "label": "CLAIMED_DEFAULT",
                    "value_inr": 100,
                    "date": None,
                    "party_id": "A1",
                    "fact_id": "F1",
                }
            ],
        },
        "procedural_history": [],
        "lower_forum_order": {
            "exists": True,
            "forum": "NCLT",
            "result": "REJECTED",
            "directions": [],
            "reasons_summary": "<reasons>",
            "ex_parte": False,
        },
        "framed_issues": [
            {"issue_id": "I1", "question": "<question>", "statutes": ["TEST_ACT_SEC_7"], "raised_by": "PETITIONER"}
        ],
        "reliefs_sought": {"PETITIONER": ["<relief>"], "RESPONDENT": []},
        "opening_positions": {
            "PETITIONER": [{"issue_id": "I1", "ground": "<ground>", "source_paras": ["P2"]}],
            "RESPONDENT": [],
        },
    }
    base.update(change)
    return AgentViewDraft.model_validate(base)


def build(d: AgentViewDraft) -> Any:
    return build_agent_view(
        d,
        forum="NCLAT",
        decision_date=date(2002, 1, 1),
        presumptions=PRESUMPTIONS,
        visible_sources=VISIBLE,
        known_statutes=KNOWN,
        aliases=StatuteAliasTable(aliases=[]),
        date_labels=LABELS,
        pseudonyms={"Bank-K", "Company-B"},
        party_statuses=["FINANCIAL_CREDITOR", "CORPORATE_DEBTOR"],
    )


def test_code_sets_forum_date_presumptions_and_agents() -> None:
    result = build(draft())
    assert result.problems == []
    view = result.view
    assert view.metadata.forum == "NCLAT" and view.metadata.simulation_date == date(2002, 1, 1)
    assert view.presumptions == PRESUMPTIONS
    assert [p.represented_by_agent for p in view.parties] == ["LEX_P", "LEX_D"]


def test_a_source_the_agents_cannot_see_blocks_the_case() -> None:
    d = draft()
    d.record.stipulated_facts[0].source_paras = ["P3"]  # an ANALYSIS paragraph
    assert any("P3" in p for p in build(d).problems)


def test_the_decision_date_is_never_a_key_date() -> None:
    d = draft(key_dates=[{"label": "DECISION", "date": "2002-01-01", "fact_id": "F1"}])
    assert any("DECISION" in p for p in build(d).problems)


def test_an_unknown_date_label_blocks() -> None:
    d = draft(key_dates=[{"label": "WHENEVER", "date": "2001-02-03", "fact_id": "F1"}])
    assert any("WHENEVER" in p for p in build(d).problems)


def test_statutes_resolve_or_are_dropped_and_flagged() -> None:
    d = draft(statutes_invoked=["TEST_ACT_SEC_7(1)", "<NOT_IN_LAW_DB_SEC_1>"])
    result = build(d)
    assert result.view.metadata.statutes_invoked == ["TEST_ACT_SEC_7"]
    assert [f.code for f in result.flags] == ["STATUTE_NOT_IN_LAW_DB"]


def test_a_dangling_reference_blocks_instead_of_raising() -> None:
    d = draft()
    d.record.amounts[0].fact_id = "F9"
    result = build(d)
    assert result.view is None and any("F9" in p for p in result.problems)


def test_an_opening_ground_from_an_unseen_paragraph_blocks() -> None:
    d = draft()
    d.opening_positions.PETITIONER[0].source_paras = ["P3"]
    assert any("P3" in p for p in build(d).problems)


def test_a_party_pseudonym_that_was_not_assigned_blocks() -> None:
    d = draft()
    d.parties[0].pseudonym = "BANK"
    assert any("BANK" in p and "pseudonym" in p for p in build(d).problems)


def test_a_status_outside_the_vocabulary_is_flagged_not_blocked() -> None:
    d = draft()
    d.parties[0].status = "BANK"
    result = build(d)
    assert result.problems == [] and [f.code for f in result.flags] == ["PARTY_STATUS_UNLISTED"]
