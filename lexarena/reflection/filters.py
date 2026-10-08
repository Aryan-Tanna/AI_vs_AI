"""Every rule a lesson must pass before it is stored (SPEC F1, F5, F7, I3-5, I3-9; D-077). Pure.

A candidate is rejected, with the reason recorded, when:
- it rests on no issue, or on an issue the court decided on EVIDENCE (F5), or on one it made no finding on;
- its source paragraphs are not the court's paragraphs for those issues (provenance must be real);
- it names a party, a pseudonym or any distinctive word of a real name (I3-9, F7); generic words that appear in many
  names (`clerk.generic_name_words`) are not names on their own;
- it states a base rate (`memory.base_rate_markers`, I3-5);
- a PROCEDURAL_ERROR lesson names a code that side never incurred, or a LEGAL_RULE lesson is not for the bench, or an
  ADVOCACY lesson is for the bench;
- the lesson schema itself refuses it (memory routing, severity range).
Statute IDs not in the Law DB are dropped from the lesson, not invented.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

from pydantic import ValidationError

from lexarena.schemas.ground_truth import CaseGroundTruth
from lexarena.schemas.lesson import Lesson
from lexarena.schemas.reflection import LessonCandidate

EXCLUDED_DRIVER = "EVIDENCE"
MIN_NAME_WORD = 4  # literal-ok: shorter name fragments ("Ltd", "Co") are too common to mark a name


@dataclass(frozen=True)
class Context:
    case_id: str
    run_id: str
    truth: CaseGroundTruth
    party_status: dict[str, str]  # side -> the party status its lessons are keyed by
    names: list[str]  # real names and pseudonyms of this case
    generic_name_words: set[str]
    base_rate_markers: list[str]
    known_statutes: set[str]
    errors_by_side: dict[str, set[str]]  # hard-error codes each side incurred
    initial_confidence: float
    case_seq: int


@dataclass(frozen=True)
class Verdict:
    lesson: Lesson | None
    reason: str | None


def name_words(names: Iterable[str], generic: set[str]) -> set[str]:
    words: set[str] = set()
    for name in names:
        for w in re.findall(r"[A-Za-z][A-Za-z'.-]*", name):
            if len(w) >= MIN_NAME_WORD and w.lower() not in generic:
                words.add(w.lower())
    return words


def _mentions(text: str, names: list[str], words: set[str]) -> str | None:
    low = text.lower()
    for name in names:
        if name.strip() and name.lower() in low:
            return name
    tokens = set(re.findall(r"[a-z][a-z'.-]*", low))
    hit = sorted(tokens & words)
    return hit[0] if hit else None


def check(candidate: LessonCandidate, n: int, ctx: Context) -> Verdict:
    findings = {f.issue_id: f for f in ctx.truth.issue_findings}
    issues = list(dict.fromkeys(candidate.issue_ids))
    if not issues:
        return Verdict(None, "no issue")
    unknown = [i for i in issues if i not in findings]
    if unknown:
        return Verdict(None, f"issues the court made no finding on: {unknown}")
    evidence = [i for i in issues if findings[i].driver == EXCLUDED_DRIVER]
    if evidence:
        return Verdict(None, f"evidence-driven issues produce no lesson (SPEC F5): {evidence}")
    allowed_paras = {p for i in issues for p in findings[i].source_paras}
    paras = list(dict.fromkeys(candidate.source_paras))
    if not paras or any(p not in allowed_paras for p in paras):
        return Verdict(None, f"source paragraphs {paras} are not the court's for {issues}")
    text = f"{candidate.trigger}\n{candidate.lesson}"
    named = _mentions(text, ctx.names, name_words(ctx.names, ctx.generic_name_words))
    if named:
        return Verdict(None, f"names a party ({named!r})")
    low = text.lower()
    marker = next((m for m in ctx.base_rate_markers if m.lower() in low), None)
    if marker:
        return Verdict(None, f"states a base rate ({marker!r})")
    bench = candidate.for_whom == "BENCH"
    if (candidate.lesson_type == "LEGAL_RULE") != bench:
        return Verdict(None, "LEGAL_RULE lessons are for the bench, and only they are")
    if candidate.lesson_type == "PROCEDURAL_ERROR" and (
        candidate.error_code is None or candidate.error_code not in ctx.errors_by_side.get(candidate.for_whom, set())
    ):
        return Verdict(None, f"{candidate.for_whom} never incurred {candidate.error_code}")
    try:
        lesson = Lesson(
            lesson_id=f"L-{ctx.case_id}-{ctx.run_id}-{n:02d}",
            lesson_type=candidate.lesson_type,
            memory="JUDGE" if bench else "LAWYER",
            party_status=None if bench else ctx.party_status.get(candidate.for_whom),
            statute_ids=[s for s in dict.fromkeys(candidate.statute_ids) if s in ctx.known_statutes],
            error_code=candidate.error_code if candidate.lesson_type == "PROCEDURAL_ERROR" else None,
            trigger=candidate.trigger.strip(),
            lesson=candidate.lesson.strip(),
            provenance={"case_id": ctx.case_id, "issue_ids": issues, "source_paras": paras},
            driver="LAW",
            severity=candidate.severity,
            frequency=1,
            confidence=ctx.initial_confidence,
            last_retrieved_case_seq=ctx.case_seq,
            status="ACTIVE",
            created_in_run=ctx.run_id,
        )
    except ValidationError as exc:
        return Verdict(None, f"schema: {exc.errors()[0]['msg']}")
    return Verdict(lesson, None)
