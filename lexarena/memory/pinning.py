"""Which lessons are pinned into a session (ARCHITECTURE §4, §6; SPEC E6, I3-4, F6; D-077).

Lawyer lessons are keyed by party status, never by agent: whichever agent represents a FINANCIAL_CREDITOR loads the
FINANCIAL_CREDITOR lessons (F6). Selection is the same for both sides (E6):
1. filter: ACTIVE; the side's party status; a statute in common with the case, or no statute at all; and the same
   version of every statute the lesson and the case share (D-111), so a lesson learnt under the law of one period is
   never pinned into a case decided under a changed provision;
2. top: rank by weight (F4) and take at most `memory.pinned_k`;
3. explore (D-111): draw `memory.explore_k` more at random from the rest of the eligible pool, seeded by the config
   seed, the case's place in the run and the memory key, so the draw is reproducible. Without it a lesson that never
   ranks high is never used, so its confidence never moves;
all within one `memory.pinned_token_budget`. Judge lessons (LEGAL_RULE only) are filtered by statute alone.

Pinning reads; it never writes. The session records the pinned IDs, and reflection updates those lessons afterwards,
in LEARN runs only, so a FROZEN run stays frozen.
"""

from __future__ import annotations

import random
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from lexarena.memory.weights import weight
from lexarena.schemas.config import AppConfig
from lexarena.schemas.lesson import Lesson


def lesson_line(lesson: Lesson) -> str:
    return f"- When {lesson.trigger}: {lesson.lesson}"


def _tokens(text: str, cfg: AppConfig) -> float:
    return len(text) / cfg.llm.chars_per_token


@dataclass(frozen=True)
class Pinned:
    top: list[Lesson]
    explore: list[Lesson]

    @property
    def all(self) -> list[Lesson]:
        return [*self.top, *self.explore]


def same_law(lesson: Lesson, law_versions: Mapping[str, str]) -> bool:
    """True when the case sees the version of each shared statute that the lesson was learnt under (D-111)."""
    return all(law_versions.get(sid, v) == v for sid, v in lesson.law_versions.items())


def usable(
    lessons: Iterable[Lesson],
    *,
    party_status: str | None,
    statutes: set[str],
    law_versions: Mapping[str, str] | None = None,
    families: Mapping[str, str] | None = None,
    unkeyed: set[str] | None = None,
) -> list[Lesson]:
    """The lessons a reader may use in this case: the filter of step 1 (also used by the agents' LESSONS lookups).
    `families` (D-139): party status -> family; a lesson of another status in the same family is usable too.
    `unkeyed` (D-139): statute IDs that never key a lesson (the appeal provisions); a lesson keyed only on them is a
    general lesson."""
    versions = law_versions or {}
    fam = families or {}
    skip = unkeyed or set()

    def same_side(status: str | None) -> bool:
        if party_status is None or status == party_status:
            return True
        return status is not None and fam.get(status) is not None and fam.get(status) == fam.get(party_status)

    return [
        x
        for x in lessons
        if x.status == "ACTIVE"
        and same_side(x.party_status)
        and (not (keys := set(x.statute_ids) - skip) or statutes & keys)
        and same_law(x, versions)
    ]


def pin(
    lessons: Iterable[Lesson],
    *,
    party_status: str | None,
    statutes: set[str],
    case_seq: int,
    cfg: AppConfig,
    law_versions: Mapping[str, str] | None = None,
    unkeyed: set[str] | None = None,
) -> Pinned:
    m = cfg.memory
    eligible = usable(
        lessons,
        party_status=party_status,
        statutes=statutes - (unkeyed or set()),
        law_versions=law_versions,
        families=m.family_of(),
        unkeyed=unkeyed,
    )
    spent = 0.0

    def fits(lesson: Lesson) -> bool:
        nonlocal spent
        cost = _tokens(lesson_line(lesson), cfg)
        if spent + cost > m.pinned_token_budget:
            return False
        spent += cost
        return True

    ranked = sorted(eligible, key=lambda x: (-weight(x, case_seq, m), x.lesson_id))
    top: list[Lesson] = []
    for lesson in ranked:
        if len(top) >= m.pinned_k:
            break
        if fits(lesson):
            top.append(lesson)
    chosen = {x.lesson_id for x in top}
    rest = sorted((x for x in eligible if x.lesson_id not in chosen), key=lambda x: x.lesson_id)
    rng = random.Random(f"{cfg.seed}:{case_seq}:{party_status or 'JUDGE'}")
    explore: list[Lesson] = []
    for lesson in rng.sample(rest, len(rest)):
        if len(explore) >= m.explore_k:
            break
        if fits(lesson):
            explore.append(lesson)
    return Pinned(top=top, explore=explore)


def select(
    lessons: Iterable[Lesson],
    *,
    party_status: str | None,
    statutes: set[str],
    case_seq: int,
    cfg: AppConfig,
    law_versions: Mapping[str, str] | None = None,
) -> list[Lesson]:
    return pin(
        lessons, party_status=party_status, statutes=statutes, case_seq=case_seq, cfg=cfg, law_versions=law_versions
    ).all


def render(lessons: list[Lesson]) -> str:
    return "\n".join(lesson_line(x) for x in lessons) or "(none)"
