"""Which lessons are pinned into a session (ARCHITECTURE §4, §6; SPEC E6, I3-4, F6; D-077).

Lawyer lessons are keyed by party status, never by agent: whichever agent represents a FINANCIAL_CREDITOR loads the
FINANCIAL_CREDITOR lessons (F6). Selection is the same for both sides (E6): filter first (ACTIVE; the side's party
status; a statute in common with the case, or no statute at all), then rank by weight (F4), then take at most
`memory.pinned_k` within `memory.pinned_token_budget`. Judge lessons (LEGAL_RULE only) are filtered by statute alone.

Pinning reads; it never writes. The session records the pinned IDs, and reflection updates those lessons afterwards,
in LEARN runs only, so a FROZEN run stays frozen.
"""

from __future__ import annotations

from collections.abc import Iterable

from lexarena.memory.weights import weight
from lexarena.schemas.config import AppConfig
from lexarena.schemas.lesson import Lesson


def lesson_line(lesson: Lesson) -> str:
    return f"- When {lesson.trigger}: {lesson.lesson}"


def _tokens(text: str, cfg: AppConfig) -> float:
    return len(text) / cfg.llm.chars_per_token


def select(
    lessons: Iterable[Lesson],
    *,
    party_status: str | None,
    statutes: set[str],
    case_seq: int,
    cfg: AppConfig,
) -> list[Lesson]:
    m = cfg.memory
    eligible = [
        x
        for x in lessons
        if x.status == "ACTIVE"
        and (party_status is None or x.party_status == party_status)
        and (not x.statute_ids or statutes & set(x.statute_ids))
    ]
    ranked = sorted(eligible, key=lambda x: (-weight(x, case_seq, m), x.lesson_id))
    chosen: list[Lesson] = []
    spent = 0.0
    for lesson in ranked:
        if len(chosen) >= m.pinned_k:
            break
        cost = _tokens(lesson_line(lesson), cfg)
        if spent + cost > m.pinned_token_budget:
            continue
        chosen.append(lesson)
        spent += cost
    return chosen


def render(lessons: list[Lesson]) -> str:
    return "\n".join(lesson_line(x) for x in lessons) or "(none)"
