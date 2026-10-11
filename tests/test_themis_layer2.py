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


CONFIRM_ALL = {"checks": [{"item": 1, "verdict": "CONFIRMED", "reason": "<r>"}]}


def run_review(
    answer: dict[str, Any], opponent: str | None = "<opponent>", confirm: dict[str, Any] | None = CONFIRM_ALL
) -> Layer2Result:
    llm, _, verifier = client([], [answer] + ([confirm] if confirm is not None else []))
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
    out = run_review(review([bad]), confirm=None)  # never reaches the second check
    assert out.hard_errors == [] and [w.code for w in out.warnings] == ["UNMAPPED"]


def test_a_flag_the_second_check_rejects_only_warns() -> None:
    """D-105 (review B2): DEV2_E2E_1 rejected '100% CoC approval', an inference the review prompt excludes."""
    found = issue("NOT_IN_RECORD", "The debtor wrote the letter", ["F1"])
    out = run_review(review([found]), confirm={"checks": [{"item": 1, "verdict": "NOT_CONFIRMED", "reason": "<r>"}]})
    assert out.hard_errors == [] and [w.code for w in out.warnings] == ["UNMAPPED"]
    assert "second check" in (out.warnings[0].detail or "")


def test_a_flag_the_second_check_skips_still_rejects() -> None:
    """Fail closed: a statement the confirmation omits keeps the first reviewer's verdict (no hallucination path)."""
    found = issue("NOT_IN_RECORD", "The debtor wrote the letter", ["F1"])
    out = run_review(review([found]), confirm={"checks": []})
    assert [p.code for p in out.hard_errors] == ["ERR_FACT_NOT_IN_RECORD"]


def test_the_second_check_sees_only_the_flagged_statements() -> None:
    found = issue("NOT_IN_RECORD", "The debtor wrote the letter", ["F1"])
    llm, _, verifier = client([], [review([found]), CONFIRM_ALL])
    review_fidelity(llm, PROMPTS, CFG, agent_view(), ARGUMENT, None, Layer2Result(), session_id="S")
    sent = verifier.requests[1].messages[-1].content
    assert "1. " in sent and "The debtor wrote the letter" in sent and ARGUMENT not in sent


def test_responsiveness_is_the_share_of_opponent_points_answered() -> None:
    out = run_review(review([], [("<a>", True), ("<b>", False), ("<c>", True), ("<d>", True)]), confirm=None)
    assert out.responsiveness == 0.75
    assert (
        run_review(review([], [("<a>", False)]), opponent=None, confirm=None).responsiveness is None
    )  # nothing to answer yet


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


def test_the_fidelity_reviewer_sees_who_the_parties_are() -> None:
    """DEV2_E2E_1: "Company-T is an operational creditor" was rejected as not in the record because the reviewer
    was shown the facts but not the parties list the lawyers see."""
    from lexarena.themis_local.layer2 import render_record

    case = agent_view()
    text = render_record(case)
    for p in case.parties:
        assert f"{p.pseudonym}: {p.status}" in text


def test_the_fidelity_reviewer_sees_the_lower_order_history_and_background() -> None:
    """DEV7_E2E_1: the appellant was rejected 3 times for stating the lower forum's reason, which the lower-order
    summary the lawyers see gives word for word; the reviewer was never shown it (D-108). The appellant attacks the
    lower order, so the gap fell on one side."""
    from lexarena.themis_local.layer2 import render_record

    case = agent_view()
    text = render_record(case)
    assert case.factual_background in text
    for s in case.procedural_history:
        assert s.event in text
    lower = case.lower_forum_order
    if lower.exists:
        assert (lower.reasons_summary or "") in text and all(d in text for d in lower.directions)


# ---------------------------------------------------------------- repetition


HARD_REPETITION = CFG.model_copy(
    update={"themis_local": CFG.themis_local.model_copy(update={"repetition_hard_error": True})}
)


def test_repetition_only_warns_under_the_v1_config() -> None:
    """D-105 (review B1): whole-text similarity cannot tell repetition from same-case argument (0.91-0.96 measured
    between honest turns), so it never rejects a draft."""
    out = Layer2Result()
    check_repetition(WordEmbedder(), ARGUMENT, [ARGUMENT], CFG, out)
    assert out.hard_errors == [] and [w.code for w in out.warnings] == ["WARN_REPETITION"]


def test_repeating_an_earlier_turn_is_a_hard_error_and_near_repeats_warn() -> None:
    out = Layer2Result()
    check_repetition(WordEmbedder(), ARGUMENT, [ARGUMENT], HARD_REPETITION, out)
    assert [p.code for p in out.hard_errors] == ["ERR_REPEATED_ARGUMENT"]
    fresh = Layer2Result()
    check_repetition(WordEmbedder(), ARGUMENT, [], HARD_REPETITION, fresh)
    assert fresh.hard_errors == [] and fresh.repetition is None


def test_a_closing_that_repeats_an_earlier_turn_only_warns() -> None:
    """R-037, D-103: a closing summarises by design, so repetition there is a warning, never a rejection."""
    out = Layer2Result()
    check_repetition(WordEmbedder(), ARGUMENT, [ARGUMENT], HARD_REPETITION, out, closing=True)
    assert out.hard_errors == [] and [w.code for w in out.warnings] == ["WARN_REPETITION"]


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

    turn = verify_with_retries(write, lambda d, last: next(results), CFG.themis_local)
    assert notes[0] is None and "ERR_FACT_NOT_IN_RECORD [T01-C1, F1]" in (notes[1] or "")
    assert (turn.result.outcome, turn.result.attempts, turn.flags) == ("PASS_WITH_NOTES", 2, [])
    assert turn.result.hard_errors_by_attempt == [["ERR_FACT_NOT_IN_RECORD"], []]
    assert turn.draft.text == "<draft 2>"


def test_a_hard_error_left_after_the_retry_cap_is_flagged_and_visible() -> None:
    calls: list[int] = []

    def write(note: str | None) -> LawyerDraft:
        calls.append(1)
        return draft(len(calls))

    turn = verify_with_retries(write, lambda d, last: verification("ERR_PRECEDENT_MISATTRIBUTED"), CFG.themis_local)
    assert len(calls) == CFG.themis_local.retry_cap + 1
    assert turn.result.outcome == "FLAGGED"
    assert [(f.code, f.claim_ids) for f in turn.flags] == [("ERR_PRECEDENT_MISATTRIBUTED", ["T01-C1"])]


def test_warnings_alone_never_trigger_a_retry() -> None:
    turn = verify_with_retries(lambda n: draft(1), lambda d, last: verification(warnings=3), CFG.themis_local)
    assert (turn.result.outcome, turn.result.attempts) == ("PASS_WITH_NOTES", 1)


def test_only_spec_d8_codes_may_reject() -> None:
    with pytest.raises(UnknownHardErrorError):
        verify_with_retries(lambda n: draft(1), lambda d, last: verification("ERR_INVENTED"), CFG.themis_local)


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
            CONFIRM_ALL,  # the second check agrees (D-105)
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
    assert len(verifier.requests) == 4


# ---------------------------------------------------------------- short circuit (D-100)


def test_only_the_last_attempt_is_marked_last() -> None:
    seen: list[bool] = []

    def check(d: LawyerDraft, last: bool) -> Verification:
        seen.append(last)
        return verification("ERR_REPEATED_ARGUMENT")

    verify_with_retries(lambda n: draft(1), check, CFG.themis_local)
    assert seen == [False] * CFG.themis_local.retry_cap + [True]


def _short_circuit_case(short_circuit: bool) -> tuple[Verification, int]:
    llm, _, verifier = client(
        [],
        [
            {"checklists": []},
            review([], [("<p>", True)]),
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
        claims=[claim(record_ids=["F999"]), claim(type="LAW", statute_id=STATUTE, precedent_ids=["P1"])],
    )
    v = ThemisLocal(llm, PROMPTS, CFG, WordEmbedder()).check(d, ctx, session_id="S", short_circuit=short_circuit)
    return v, len(verifier.requests)


def test_a_draft_the_free_checks_reject_skips_the_paid_checks() -> None:
    v, calls = _short_circuit_case(short_circuit=True)
    assert [p.code for p in v.hard_errors] == ["ERR_FACT_NOT_IN_RECORD"] and calls == 0


def test_the_last_attempt_always_runs_every_check() -> None:
    v, calls = _short_circuit_case(short_circuit=False)
    assert "ERR_FACT_NOT_IN_RECORD" in [p.code for p in v.hard_errors] and calls == 3
