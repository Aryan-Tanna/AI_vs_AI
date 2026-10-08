"""The clerk end to end with scripted model answers (BUILD_PLAN Step 6, D-056 to D-059). Placeholder pages only:
the point is the wiring, the checks between steps and what comes out, not any real judgment."""

from __future__ import annotations

import json
from datetime import date
from typing import Any

from lexarena.app import PROMPTS_ROOT
from lexarena.clerk.pipeline import clerk_judgment
from lexarena.clerk.review import render_review
from lexarena.config import load_config
from lexarena.llm.client import LLMClient
from lexarena.prompts import PromptStore
from lexarena.schemas.statute_alias import StatuteAliasTable
from lexarena.secrets import SecretStore
from tests.conftest import CONFIG_V1
from tests.fakes import FakeProvider, text_response

PAGES = [
    "<Tribunal>\nAppeal No. 77 of 2001\nZorvex Quillon Bank ...Appellant\nVersus\n"
    "Pellam Tarsh Seeds Ltd ...Respondent\n"
    "JUDGMENT\n1. Zorvex Quillon Bank appeals an order of 05.05.2000 rejecting its application.\n"
    "2. Counsel for Zorvex Quillon Bank submits that a letter of 03.03.1999 acknowledged the debt.\n"
    "3. The default date is recorded as 01.01.1998. We are of the view that the application is barred. "
    "The appeal is dismissed."
]
ENTITIES = {
    "entities": [
        {"name": "Zorvex Quillon Bank", "variants": [], "kind": "BANK", "cause_title_role": "APPELLANT"},
        {"name": "Pellam Tarsh Seeds Ltd", "variants": [], "kind": "COMPANY", "cause_title_role": "RESPONDENT"},
    ]
}
ROUTE = {
    "labels": [
        {"para_id": "P1", "part": "FACTS"},
        {"para_id": "P2", "part": "SUBMISSIONS_P"},
        {"para_id": "P3", "part": "ANALYSIS"},
    ]
}
RECORD_FACTS = {"record_fact_ids": ["P3.S1"]}


def view_answer(bank: str, company: str) -> dict[str, Any]:
    return {
        "proceeding_type": "APPEAL_UNDER_SEC_61",
        "statutes_invoked": ["TEST_ACT_SEC_7"],
        "key_dates": [{"label": "DEFAULT", "date": "1998-01-01", "fact_id": "F1"}],
        "parties": [
            {
                "party_id": "A1",
                "pseudonym": bank,
                "status": "FINANCIAL_CREDITOR",
                "simulation_side": "PETITIONER",
                "appeal_position": "APPELLANT",
                "substituted_from": None,
            },
            {
                "party_id": "R1",
                "pseudonym": company,
                "status": "CORPORATE_DEBTOR",
                "simulation_side": "RESPONDENT",
                "appeal_position": "RESPONDENT_1",
                "substituted_from": None,
            },
        ],
        "factual_background": "The default date is recorded as 01.01.1998 [F1].",
        "record": {
            "stipulated_facts": [
                {"fact_id": "F1", "text": "The default date is recorded as 01.01.1998.", "source_paras": ["P3.S1"]}
            ],
            "contested_facts": [],
            "exhibits": [
                {
                    "exhibit_id": "EX-1",
                    "title": "<letter>",
                    "filed_by": "A1",
                    "known_contents": ["acknowledged the debt"],
                    "contents_beyond_known": "UNKNOWN",
                    "authenticity": "PRESUMED",
                    "source_paras": ["P2"],
                }
            ],
            "amounts": [],
        },
        "procedural_history": [],
        "lower_forum_order": {
            "exists": True,
            "forum": "NCLT",
            "result": "REJECTED",
            "directions": [],
            "reasons_summary": "The application was rejected.",
            "ex_parte": None,
        },
        "framed_issues": [
            {
                "issue_id": "I1",
                "question": "Whether the letter extends limitation.",
                "statutes": ["TEST_ACT_SEC_7"],
                "raised_by": "PETITIONER",
            }
        ],
        "reliefs_sought": {"PETITIONER": ["Set aside the order"], "RESPONDENT": ["Dismiss the appeal"]},
        "opening_positions": {
            "PETITIONER": [{"issue_id": "I1", "ground": "The letter acknowledged the debt.", "source_paras": ["P2"]}],
            "RESPONDENT": [{"issue_id": "I1", "ground": "The application was rejected.", "source_paras": ["P1"]}],
        },
    }


TRUTH = {
    "citation": {
        "case_number": "Appeal No. 77 of 2001",
        "arising_from": None,
        "bench": ["<member>"],
        "decision_date": "2002-02-02",
        "source_title": "<title>",
    },
    "real_submissions": {"PETITIONER": [], "RESPONDENT": []},
    "statutory_analysis": [],
    "precedent_analysis": [],
    "issue_findings": [
        {
            "issue_id": "I1",
            "favours": "RESPONDENT",
            "driver": "LAW",
            "finding": "<finding>",
            "reasoning": "<reasoning>",
            "test_applied": "<test>",
            "decisive_points": [],
            "authorities_relied_on": [],
            "source_paras": ["P3"],
        }
    ],
    "conclusion": {
        "disposition": "DISMISSED",
        "reliefs": [{"relief": "Set aside the order", "sought_by": "PETITIONER", "outcome": "REFUSED"}],
        "directions": [],
        "costs": None,
        "overall_favours": "RESPONDENT",
    },
}
ENTAILMENT = {
    "verdicts": [
        {"item_id": i, "verdict": "SUPPORTED", "reason": "<r>"}
        for i in ("F1", "EX-1", "PETITIONER-G1", "RESPONDENT-G1")
    ]
}
PROBE = {"recognised": False, "case_name": None, "appeal_number": None, "outcome": None}
PRECEDENTS = [
    {
        "precedent_id": "P-SAME-CD",
        "precedent_uid": "P-SAME-CD#u",
        "case_title": "X vs. Pellam Tarsh Seeds Ltd",
        "appeal_number": "<n>",
        "decision_date": "1999-01-01",
    },
    {
        "precedent_id": "P-OTHER",
        "precedent_uid": "P-OTHER#u",
        "case_title": "Qarno vs. Vell",
        "appeal_number": "<n>",
        "decision_date": "1999-01-01",
    },
]


def run() -> Any:
    cfg = load_config(CONFIG_V1)
    from lexarena.clerk.names import assign_pseudonyms
    from lexarena.schemas.clerk import EntityList

    assigned = assign_pseudonyms(EntityList.model_validate(ENTITIES).entities, case_key="DEV_T", seed=cfg.seed)
    bank, company = (a.pseudonym for a in assigned)
    gemini = FakeProvider(
        [text_response(json.dumps(x)) for x in (ENTITIES, ROUTE, RECORD_FACTS, view_answer(bank, company), TRUTH)]
    )
    groq = FakeProvider([text_response(json.dumps(x)) for x in (ENTAILMENT, PROBE)])
    names = {m.api_key_env for m in cfg.models.by_role().values()}
    llm = LLMClient(
        cfg,
        SecretStore(env_file=None, environ={n: "k" for n in names}),
        PromptStore(PROMPTS_ROOT),
        providers={"gemini": gemini, "groq": groq},
        cache=None,
        sleep=lambda _: None,
    )
    outcome = clerk_judgment(
        PAGES,
        source_file="<file>.pdf",
        source_bytes=b"<pdf bytes>",
        case_id="DEV_T",
        forum="NCLAT",
        decided=date(2002, 2, 2),
        split_name="DEV",
        llm=llm,
        prompts=PromptStore(PROMPTS_ROOT),
        cfg=cfg,
        known_statutes={"TEST_ACT_SEC_7"},
        aliases=StatuteAliasTable(aliases=[]),
        precedent_payloads=PRECEDENTS,
    )
    return outcome, gemini, groq, bank, company


def test_a_clean_case_comes_out_whole_and_storable() -> None:
    outcome, _, _, _, _ = run()
    assert outcome.problems == [], outcome.problems
    assert outcome.case is not None and outcome.truth is not None
    assert outcome.case.build.excluded_precedent_ids == ["P-SAME-CD"]
    assert outcome.case.build.memorization_probe == "NOT_IDENTIFIED"
    assert outcome.case.build.evidence_dependency == "LAW_ONLY"
    assert [p.part for p in outcome.judgment.paragraphs] == ["FACTS", "SUBMISSIONS_P", "ANALYSIS"]
    assert outcome.truth.anonymization_map  # pseudonym -> real name, sealed


def test_the_extractor_never_sees_real_names_or_the_reasoning() -> None:
    _, gemini, _, bank, _ = run()
    extractor_prompt = gemini.requests[3].messages[-1].content
    assert "Zorvex" not in extractor_prompt and bank in extractor_prompt
    assert "We are of the view" not in extractor_prompt and "The appeal is dismissed" not in extractor_prompt
    assert "[P3.S1] The default date is recorded as 01.01.1998." in extractor_prompt


def test_the_second_family_checks_and_the_lawyer_model_is_probed() -> None:
    _, _, groq, _, _ = run()
    assert [r.model.name for r in groq.requests] == ["openai/gpt-oss-120b", "openai/gpt-oss-120b"]
    assert "Zorvex" not in groq.requests[1].messages[-1].content  # the probe sees the pseudonymised case


def test_the_review_file_lists_items_with_their_sources() -> None:
    outcome, _, _, _, _ = run()
    text = render_review(outcome, "<file>.pdf")
    assert "- [ ] **F1** The default date is recorded as 01.01.1998." in text
    assert "> **P3.S1**: The default date is recorded as 01.01.1998." in text
    assert "P-SAME-CD" in text and "Zorvex" not in text


def test_one_repair_round_fixes_an_unsupported_item_and_everything_is_checked_again() -> None:
    cfg = load_config(CONFIG_V1)
    from lexarena.clerk.names import assign_pseudonyms
    from lexarena.schemas.clerk import EntityList

    assigned = assign_pseudonyms(EntityList.model_validate(ENTITIES).entities, case_key="DEV_T", seed=cfg.seed)
    bank, company = (a.pseudonym for a in assigned)
    first = view_answer(bank, company)
    repaired = json.loads(json.dumps(first))
    repaired["opening_positions"]["RESPONDENT"] = []
    bad = {
        "verdicts": [
            {"item_id": i, "verdict": "NOT_SUPPORTED" if i == "RESPONDENT-G1" else "SUPPORTED", "reason": "<r>"}
            for i in ("F1", "EX-1", "PETITIONER-G1", "RESPONDENT-G1")
        ]
    }
    good = {
        "verdicts": [{"item_id": i, "verdict": "SUPPORTED", "reason": "<r>"} for i in ("F1", "EX-1", "PETITIONER-G1")]
    }
    gemini = FakeProvider(
        [text_response(json.dumps(x)) for x in (ENTITIES, ROUTE, RECORD_FACTS, first, repaired, TRUTH)]
    )
    groq = FakeProvider([text_response(json.dumps(x)) for x in (bad, good, PROBE)])
    names = {m.api_key_env for m in cfg.models.by_role().values()}
    llm = LLMClient(
        cfg,
        SecretStore(env_file=None, environ={n: "k" for n in names}),
        PromptStore(PROMPTS_ROOT),
        providers={"gemini": gemini, "groq": groq},
        cache=None,
        sleep=lambda _: None,
    )
    outcome = clerk_judgment(
        PAGES,
        source_file="<f>",
        source_bytes=b"<b>",
        case_id="DEV_T",
        forum="NCLAT",
        decided=date(2002, 2, 2),
        split_name="DEV",
        llm=llm,
        prompts=PromptStore(PROMPTS_ROOT),
        cfg=cfg,
        known_statutes={"TEST_ACT_SEC_7"},
        aliases=StatuteAliasTable(aliases=[]),
        precedent_payloads=[],
    )
    assert outcome.problems == []
    assert any(f.code == "EXTRACTION_REPAIRED" for f in outcome.flags)
    repair_prompt = gemini.requests[4].messages[-1].content
    assert "RESPONDENT-G1 is not supported" in repair_prompt
    assert bank in groq.requests[0].messages[-1].content  # the verifier gets the party roster
