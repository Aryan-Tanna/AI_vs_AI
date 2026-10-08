"""THEMIS-LOCAL layer 2 and the outcome policy (BUILD_PLAN Step 8; SPEC A2, B4, D4, D7, D8; D-075). Offline: the
verifier is scripted, precedents come from a fake fetch tool, embeddings from a word hash."""

from __future__ import annotations

from typing import Any

import pytest

from lexarena.prompts import PromptStore
from lexarena.schemas.agent import DraftClaim, LawyerDraft
from lexarena.schemas.retrieval import PrecedentExcerpt
from lexarena.themis_local.layer2 import (
    Layer2Result,
    Problem,
    check_citations,
    check_claim_references,
    check_repetition,
    record_index,
    review_fidelity,
)
from lexarena.themis_local.outcome import UnknownHardErrorError, feedback, verify_with_retries
from lexarena.themis_local.verify import LawContext, ThemisLocal, Verification, VerifyContext
from tests import builders
from tests.conftest import PROMPTS_ROOT
from tests.fakes import WordEmbedder
from tests.judge_fixtures import CFG, STATUTE, agent_view, client
from tests.test_layer1 import statute_view

PROMPTS = PromptStore(PROMPTS_ROOT)
RATIO = "An acknowledgment of liability in writing before the period expires starts a fresh period of limitation."
ARGUMENT = "The debtor wrote the letter in EX-1 admitting the debt. The letter also promised payment of Rs 9 crore."


def claim(**change: Any) -> DraftClaim:
    base: dict[str, Any] = {
        "type": "FACT",
        "text": "<claim>",
        "record_ids": ["F1"],
        "statute_id": None,
        "precedent_ids": [],
    }
    return DraftClaim.model_validate({**base, **change})


def fetch(uid: str, part: str = "ratio") -> PrecedentExcerpt | None:
    if uid != "P1":
        return None
    return PrecedentExcerpt(
        precedent_uid=uid,
        precedent_id="<id>",
        case_title="<title>",
        decision_date=builders.PLACEHOLDER_DATE,
        part="ratio",
        text=RATIO,
    )


def issue(kind: str, quote: str, ids: list[str], confidence: float = 0.9) -> dict[str, Any]:
    return {"kind": kind, "quote": quote, "record_ids": ids, "explanation": "<why>", "confidence": confidence}


def review(issues: list[dict[str, Any]], points: list[tuple[str, bool]] | None = None) -> dict[str, Any]:
    return {"fidelity_issues": issues, "opponent_points": [{"point": p, "addressed": a} for p, a in points or []]}


def run_review(answer: dict[str, Any], opponent: str | None = "<opponent>") -> Layer2Result:
    llm, _, verifier = client([], [answer])
    out = Layer2Result()
    review_fidelity(llm, PROMPTS, CFG, agent_view(), ARGUMENT, opponent, out, session_id="S")
    assert verifier.requests[0].model.temperature == 0
    return out


# ---------------------------------------------------------------- claim references


def test_a_claim_citing_a_record_id_that_does_not_exist_is_a_hard_error() -> None:
    out = Layer2Result()
    claims = [
        ("T01-C1", claim(record_ids=["F1", "F99"])),
        ("T01-C2", claim(type="LAW", statute_id="<unknown statute>")),
    ]
    check_claim_references(claims, record_index(agent_view()), {STATUTE}, out)
    assert [(p.code, p.record_ids, p.claim_ids) for p in out.hard_errors] == [
        ("ERR_FACT_NOT_IN_RECORD", ["F99"], ["T01-C1"])
    ]
    assert [w.code for w in out.warnings] == ["STATUTE_NOT_AVAILABLE"]


# ---------------------------------------------------------------- record fidelity


def test_a_fabricated_exhibit_quoted_verbatim_is_caught() -> None:
    out = run_review(
        review([issue("EXHIBIT_CONTENT_FABRICATED", "The letter also promised payment of Rs 9 crore.", ["EX-1"])])
    )
    assert [p.code for p in out.hard_errors] == ["ERR_EXHIBIT_CONTENT_FABRICATED"]
    assert out.hard_errors[0].record_ids == ["EX-1"]


@pytest.mark.parametrize(
    "bad",
    [
        issue("NOT_IN_RECORD", "words the argument never used", ["F1"]),  # not verbatim
        issue("NOT_IN_RECORD", "The debtor wrote the letter", ["F42"]),  # names no real record item
        issue("NOT_IN_RECORD", "The debtor wrote the letter", ["F1"], confidence=0.1),  # not confident
        issue("EXHIBIT_CONTENT_FABRICATED", "The debtor wrote the letter", ["F1"]),  # exhibit kind without an exhibit
    ],
)
def test_unconfirmed_fidelity_findings_only_warn(bad: dict[str, Any]) -> None:
    out = run_review(review([bad]))
    assert out.hard_errors == [] and [w.code for w in out.warnings] == ["UNMAPPED"]


def test_responsiveness_is_the_share_of_opponent_points_answered() -> None:
    out = run_review(review([], [("<a>", True), ("<b>", False), ("<c>", True), ("<d>", True)]))
    assert out.responsiveness == 0.75
    assert run_review(review([], [("<a>", False)]), opponent=None).responsiveness is None  # nothing to answer yet


# ---------------------------------------------------------------- citations


def verdict(cid: str, uid: str, v: str, quote: str = "") -> dict[str, Any]:
    return {"claim_id": cid, "precedent_uid": uid, "verdict": v, "ratio_quote": quote}


def run_citations(
    claims: list[tuple[str, DraftClaim]], verdicts: list[dict[str, Any]] | None
) -> tuple[Layer2Result, Any]:
    llm, _, verifier = client([], [{"verdicts": verdicts}] if verdicts is not None else [])
    out = Layer2Result()
    check_citations(llm, PROMPTS, CFG, claims, fetch, out, session_id="S")
    return out, verifier


def test_an_inverted_holding_quoted_from_the_ratio_is_caught() -> None:
    claims = [("T01-C1", claim(type="LAW", text="An acknowledgment never restarts limitation.", precedent_ids=["P1"]))]
    out, _ = run_citations(claims, [verdict("T01-C1", "P1", "CONTRADICTS", "starts a fresh period of limitation")])
    assert [p.code for p in out.hard_errors] == ["ERR_PRECEDENT_MISATTRIBUTED"]
    assert out.assessments[0].entailment == "CONTRADICTS"


def test_a_contradiction_without_a_verbatim_ratio_quote_only_warns() -> None:
    claims = [("T01-C1", claim(type="LAW", precedent_ids=["P1"]))]
    out, _ = run_citations(claims, [verdict("T01-C1", "P1", "CONTRADICTS", "words not in the ratio")])
    assert out.hard_errors == [] and [w.code for w in out.warnings] == ["WARN_PRECEDENT_NOT_ADDRESSED"]


def test_unverifiable_citations_warn_and_never_call_the_verifier() -> None:
    out, verifier = run_citations([("T01-C1", claim(type="LAW", precedent_ids=["<excluded>"]))], None)
    assert out.hard_errors == [] and [w.code for w in out.warnings] == ["WARN_UNVERIFIABLE_CITATION"]
    assert out.assessments[0].citation_tier == "UNVERIFIABLE" and verifier.requests == []


def test_a_supported_citation_is_verified_in_one_batched_call() -> None:
    claims = [("T01-C1", claim(type="LAW", precedent_ids=["P1"])), ("T01-C2", claim(type="LAW", precedent_ids=["P1"]))]
    out, verifier = run_citations(claims, [verdict("T01-C1", "P1", "SUPPORTS"), verdict("T01-C2", "P1", "SUPPORTS")])
    assert [a.citation_tier for a in out.assessments] == ["VERIFIED", "VERIFIED"]
    assert len(verifier.requests) == 1 and RATIO in verifier.requests[0].messages[-1].content


# ---------------------------------------------------------------- repetition


def test_repeating_an_earlier_turn_is_a_hard_error_and_near_repeats_warn() -> None:
    out = Layer2Result()
    check_repetition(WordEmbedder(), ARGUMENT, [ARGUMENT], CFG, out)
    assert [p.code for p in out.hard_errors] == ["ERR_REPEATED_ARGUMENT"]
    fresh = Layer2Result()
    check_repetition(WordEmbedder(), ARGUMENT, [], CFG, fresh)
    assert fresh.hard_errors == [] and fresh.repetition is None


# ---------------------------------------------------------------- outcome policy


def verification(*codes: str, warnings: int = 0) -> Verification:
    from lexarena.schemas.transcript import ThemisWarning

    v = Verification(claims=[])
    v.hard_errors = [Problem(c, "<detail>", ["F1"], ["T01-C1"]) for c in codes]
    v.warnings = [ThemisWarning(code="UNMAPPED") for _ in range(warnings)]
    return v


def draft(n: int) -> LawyerDraft:
    return LawyerDraft(text=f"<draft {n}>", issues_addressed=["I1"], claims=[])


def test_retry_feeds_back_exact_codes_and_ids_then_passes() -> None:
    notes: list[str | None] = []
    results = iter([verification("ERR_FACT_NOT_IN_RECORD"), verification(warnings=1)])

    def write(note: str | None) -> LawyerDraft:
        notes.append(note)
        return draft(len(notes))

    turn = verify_with_retries(write, lambda d: next(results), CFG.themis_local)
    assert notes[0] is None and "ERR_FACT_NOT_IN_RECORD [T01-C1, F1]" in (notes[1] or "")
    assert (turn.result.outcome, turn.result.attempts, turn.flags) == ("PASS_WITH_NOTES", 2, [])
    assert turn.result.hard_errors_by_attempt == [["ERR_FACT_NOT_IN_RECORD"], []]
    assert turn.draft.text == "<draft 2>"


def test_a_hard_error_left_after_the_retry_cap_is_flagged_and_visible() -> None:
    calls: list[int] = []

    def write(note: str | None) -> LawyerDraft:
        calls.append(1)
        return draft(len(calls))

    turn = verify_with_retries(write, lambda d: verification("ERR_PRECEDENT_MISATTRIBUTED"), CFG.themis_local)
    assert len(calls) == CFG.themis_local.retry_cap + 1
    assert turn.result.outcome == "FLAGGED"
    assert [(f.code, f.claim_ids) for f in turn.flags] == [("ERR_PRECEDENT_MISATTRIBUTED", ["T01-C1"])]


def test_warnings_alone_never_trigger_a_retry() -> None:
    turn = verify_with_retries(lambda n: draft(1), lambda d: verification(warnings=3), CFG.themis_local)
    assert (turn.result.outcome, turn.result.attempts) == ("PASS_WITH_NOTES", 1)


def test_only_spec_d8_codes_may_reject() -> None:
    with pytest.raises(UnknownHardErrorError):
        verify_with_retries(lambda n: draft(1), lambda d: verification("ERR_INVENTED"), CFG.themis_local)


def test_feedback_lists_each_problem() -> None:
    text = feedback([Problem("ERR_TIMELINE_MISSTATED", "<d>", ["F4"]), Problem("ERR_REPEATED_ARGUMENT", "<e>")])
    assert text.splitlines() == ["- ERR_TIMELINE_MISSTATED [F4]: <d>", "- ERR_REPEATED_ARGUMENT: <e>"]


# ---------------------------------------------------------------- the whole check


def test_the_whole_check_runs_layer_1_and_layer_2() -> None:
    llm, _, verifier = client(
        [],
        [
            {"checklists": []},  # layer 1 extraction
            review(
                [issue("NOT_IN_RECORD", "The letter also promised payment of Rs 9 crore.", ["EX-1"])], [("<p>", True)]
            ),
            {"verdicts": [verdict("T03-C2", "P1", "SUPPORTS")]},
        ],
    )
    ctx = VerifyContext(
        case=agent_view(),
        law=LawContext(views={STATUTE: statute_view(STATUTE)}, alternatives=None, predicates={}),
        fetch_precedent=fetch,
        turn=3,
        opponent_last="<opponent>",
        own_earlier=["<a different earlier turn>"],
    )
    d = LawyerDraft(
        text=ARGUMENT,
        issues_addressed=["I1"],
        claims=[claim(record_ids=["EX-1"]), claim(type="LAW", statute_id=STATUTE, precedent_ids=["P1"])],
    )
    v = ThemisLocal(llm, PROMPTS, CFG, WordEmbedder()).check(d, ctx, session_id="S")
    assert [c for c, _ in v.claims] == ["T03-C1", "T03-C2"]
    assert [p.code for p in v.hard_errors] == ["ERR_FACT_NOT_IN_RECORD"]
    assert v.responsiveness == 1.0 and v.assessments[0].citation_tier == "VERIFIED"
    assert len(verifier.requests) == 3
