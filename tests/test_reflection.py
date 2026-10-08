"""Experience memory and reflection rules (BUILD_PLAN Step 12; SPEC F1-F7, E6, I3-4, I3-5, I3-9; D-077). Offline."""

from __future__ import annotations

from typing import Any

import pytest

from lexarena.memory.pinning import select
from lexarena.memory.weights import after_use, weakened, weight
from lexarena.reflection.dedup import place
from lexarena.reflection.filters import Context, check
from lexarena.schemas.lesson import Lesson
from lexarena.schemas.reflection import LessonCandidate
from tests import builders
from tests.judge_fixtures import CFG

M = CFG.memory


def lesson(n: int, **change: Any) -> Lesson:
    base: dict[str, Any] = {
        "lesson_id": f"L-{n}",
        "lesson_type": "ADVOCACY",
        "memory": "LAWYER",
        "party_status": "FINANCIAL_CREDITOR",
        "statute_ids": ["<statute A>"],
        "error_code": None,
        "trigger": "<trigger>",
        "lesson": f"<lesson {n}>",
        "provenance": {"case_id": "TESTCASE_0001", "issue_ids": ["I1"], "source_paras": ["1"]},
        "driver": "LAW",
        "severity": 3,
        "frequency": 1,
        "confidence": M.initial_confidence,
        "last_retrieved_case_seq": 1,
        "status": "ACTIVE",
        "created_in_run": "<run>",
    }
    return Lesson.model_validate({**base, **change})


# ---------------------------------------------------------------- weight, confidence, retirement (F4)


def test_weight_grows_with_severity_frequency_confidence_and_decays_with_disuse() -> None:
    a = lesson(1)
    assert weight(a, 1, M) > weight(a, 20, M)  # unused for 19 cases: decayed by lambda^19
    assert weight(lesson(2, severity=5), 1, M) > weight(a, 1, M)
    assert weight(lesson(3, frequency=4), 1, M) > weight(a, 1, M)


def test_confidence_follows_the_reward_of_the_cases_that_use_it() -> None:
    first = after_use(lesson(1), 0.6, 5, M)
    assert (first.confidence, first.last_reward, first.last_retrieved_case_seq) == (M.initial_confidence, 0.6, 5)
    better = after_use(first, 0.7, 6, M)
    worse = after_use(first, 0.4, 6, M)
    assert better.confidence == pytest.approx(M.initial_confidence + M.confidence_step)
    assert worse.confidence == pytest.approx(M.initial_confidence - M.confidence_step)


def test_a_lesson_below_the_floor_retires() -> None:
    low = lesson(1, confidence=M.retire_below_confidence + M.confidence_step / 2)
    assert weakened(low, M).status == "RETIRED"


# ---------------------------------------------------------------- pinning (E6, I3-4, F6)


def test_pinning_filters_by_party_status_and_statute_then_ranks_by_weight() -> None:
    pool = [
        lesson(1, severity=2),
        lesson(2, severity=5),
        lesson(3, party_status="CORPORATE_DEBTOR", severity=5),  # the other side's status
        lesson(4, statute_ids=["<statute B>"], severity=5),  # no statute in common
        lesson(5, statute_ids=[], severity=1),  # general: applies to any statute
        lesson(6, status="RETIRED", severity=5),
    ]
    chosen = select(pool, party_status="FINANCIAL_CREDITOR", statutes={"<statute A>"}, case_seq=1, cfg=CFG)
    assert [x.lesson_id for x in chosen] == ["L-2", "L-1", "L-5"]


def test_pinning_obeys_the_same_count_and_token_budget_for_everyone() -> None:
    pool = [lesson(n) for n in range(1, 20)]  # literal-ok: more lessons than K
    chosen = select(pool, party_status="FINANCIAL_CREDITOR", statutes={"<statute A>"}, case_seq=1, cfg=CFG)
    assert len(chosen) == M.pinned_k
    long = [lesson(n, lesson="x" * int(M.pinned_token_budget * CFG.llm.chars_per_token)) for n in range(1, 4)]
    assert select(long, party_status="FINANCIAL_CREDITOR", statutes={"<statute A>"}, case_seq=1, cfg=CFG) == []


# ---------------------------------------------------------------- candidate filters


def truth() -> Any:
    doc = builders.ground_truth("TESTCASE_0001", "<sentinel>").to_document()
    template = doc["issue_findings"][0]
    doc["issue_findings"] = [
        {**template, "issue_id": "I1", "driver": "LAW", "source_paras": ["P4", "P5"]},
        {**template, "issue_id": "I2", "driver": "EVIDENCE", "source_paras": ["P6"]},
    ]
    doc["anonymization_map"] = {"Bank-Y": "Imperial Mercantile Bank", "Company-H": "Harvest Agro Limited"}
    from lexarena.schemas.ground_truth import CaseGroundTruth

    return CaseGroundTruth.model_validate(doc)


def ctx() -> Context:
    t = truth()
    return Context(
        case_id="TESTCASE_0001",
        run_id="R1",
        truth=t,
        party_status={"PETITIONER": "FINANCIAL_CREDITOR", "RESPONDENT": "CORPORATE_DEBTOR"},
        names=[*t.anonymization_map, *t.anonymization_map.values()],
        generic_name_words={w.lower() for w in CFG.clerk.generic_name_words},
        base_rate_markers=M.base_rate_markers,
        known_statutes={"<statute A>"},
        errors_by_side={"PETITIONER": {"ERR_TIMELINE_MISSTATED"}, "RESPONDENT": set()},
        initial_confidence=M.initial_confidence,
        case_seq=3,
    )


def candidate(**change: Any) -> LessonCandidate:
    base: dict[str, Any] = {
        "lesson_type": "ADVOCACY",
        "for_whom": "PETITIONER",
        "statute_ids": ["<statute A>", "<invented statute>"],
        "error_code": None,
        "trigger": "the debtor argues the claim is time-barred despite written settlement offers",
        "lesson": "Lead with the written acknowledgments and the dates they restart limitation from.",
        "issue_ids": ["I1"],
        "source_paras": ["P4"],
        "severity": 4,
    }
    return LessonCandidate.model_validate({**base, **change})


def test_a_good_candidate_becomes_a_lesson_keyed_by_party_status() -> None:
    v = check(candidate(), 1, ctx())
    assert v.lesson is not None and v.reason is None
    x = v.lesson
    assert (x.memory, x.party_status, x.statute_ids, x.confidence) == (
        "LAWYER",
        "FINANCIAL_CREDITOR",
        ["<statute A>"],  # the invented statute is dropped, never kept
        M.initial_confidence,
    )
    assert x.provenance.source_paras == ["P4"] and x.last_retrieved_case_seq == 3


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ({"issue_ids": ["I2"], "source_paras": ["P6"]}, "evidence-driven"),
        ({"issue_ids": ["I9"]}, "no finding"),
        ({"source_paras": ["P99"]}, "source paragraphs"),
        ({"lesson": "Against Imperial Mercantile Bank, lead with dates."}, "names a party"),
        ({"lesson": "Bank-Y should lead with dates."}, "names a party"),
        ({"trigger": "a dispute with Harvest over offers"}, "names a party"),  # a distinctive word of a real name
        ({"lesson": "Financial creditors usually win these appeals."}, "base rate"),
        ({"lesson_type": "LEGAL_RULE"}, "bench"),
        ({"lesson_type": "ADVOCACY", "for_whom": "BENCH"}, "bench"),
        ({"lesson_type": "PROCEDURAL_ERROR", "error_code": "ERR_PRECEDENT_MISATTRIBUTED"}, "never incurred"),
        ({"severity": 9}, "schema"),
    ],
)
def test_every_rule_rejects_with_a_reason(change: dict[str, Any], reason: str) -> None:
    v = check(candidate(**change), 1, ctx())
    assert v.lesson is None and reason in (v.reason or "")


def test_generic_name_words_alone_are_not_names() -> None:
    v = check(candidate(lesson="Lead with the bank's written acknowledgments."), 1, ctx())
    assert v.lesson is not None


def test_procedural_and_legal_rule_lessons_route_correctly() -> None:
    proc = check(candidate(lesson_type="PROCEDURAL_ERROR", error_code="ERR_TIMELINE_MISSTATED"), 1, ctx()).lesson
    rule = check(candidate(lesson_type="LEGAL_RULE", for_whom="BENCH"), 2, ctx()).lesson
    assert proc is not None and (proc.memory, proc.error_code) == ("LAWYER", "ERR_TIMELINE_MISSTATED")
    assert rule is not None and (rule.memory, rule.party_status) == ("JUDGE", None)


# ---------------------------------------------------------------- dedup (F3)


def test_dedup_merges_same_keeps_opposite_apart_and_inserts_different() -> None:
    old = lesson(1)
    vec = [1.0, 0.0]
    new = lesson(2)
    merged = place(new, vec, [(old, vec)], lambda a, b: "SAME", M)
    assert merged.outcome == "MERGED into L-1" and merged.writes[0][0].frequency == 2
    opposite = place(new, vec, [(old, vec)], lambda a, b: "OPPOSITE", M)
    assert [w[0].lesson_id for w in opposite.writes] == ["L-2", "L-1"]
    assert opposite.writes[1][0].confidence == pytest.approx(M.initial_confidence - M.confidence_step)
    assert place(new, vec, [(old, vec)], lambda a, b: "DIFFERENT", M).outcome == "INSERTED"


def test_dedup_never_asks_the_model_across_keys_or_below_the_similarity_threshold() -> None:
    asked: list[int] = []

    def compare(a: Lesson, b: Lesson) -> str:
        asked.append(1)
        return "SAME"

    other_key = lesson(1, party_status="CORPORATE_DEBTOR")
    assert place(lesson(2), [1.0, 0.0], [(other_key, [1.0, 0.0])], compare, M).outcome == "INSERTED"
    assert place(lesson(2), [1.0, 0.0], [(lesson(1), [0.0, 1.0])], compare, M).outcome == "INSERTED"
    assert asked == []
