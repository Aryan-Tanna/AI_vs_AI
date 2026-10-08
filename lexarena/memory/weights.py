"""Lesson weight, confidence and retirement (SPEC F4; D-077). Pure functions; every number from config.

W = severity x log(1 + frequency) x confidence x lambda^(cases since last retrieved)

Confidence starts at `memory.initial_confidence`. When a lesson was pinned into a case, it rises by
`memory.confidence_step` if that case's reward was at least the reward of the case that last used it, and falls by the
same step otherwise (the first use only records the reward). Rewards are the F2 reward of whoever used it: the lawyer's
for lawyer lessons, the bench's issue alignment for judge lessons. Below `memory.retire_below_confidence` a lesson is
RETIRED and never pinned again.
"""

from __future__ import annotations

import math

from lexarena.schemas.config import MemoryConfig
from lexarena.schemas.lesson import Lesson


def weight(lesson: Lesson, case_seq: int, cfg: MemoryConfig) -> float:
    age = max(0, case_seq - lesson.last_retrieved_case_seq)
    return lesson.severity * math.log1p(lesson.frequency) * lesson.confidence * cfg.decay_lambda**age


def after_use(lesson: Lesson, reward: float, case_seq: int, cfg: MemoryConfig) -> Lesson:
    """The lesson after being pinned into case `case_seq`, whose reward was `reward`."""
    confidence = lesson.confidence
    if lesson.last_reward is not None:
        step = cfg.confidence_step if reward >= lesson.last_reward else -cfg.confidence_step
        confidence = min(1.0, max(0.0, confidence + step))
    return retire_if_weak(
        lesson.model_copy(
            update={"confidence": confidence, "last_reward": reward, "last_retrieved_case_seq": case_seq}
        ),
        cfg,
    )


def weakened(lesson: Lesson, cfg: MemoryConfig) -> Lesson:
    """An older lesson a newer, opposite one contradicts (SPEC F3): it loses one confidence step."""
    return retire_if_weak(
        lesson.model_copy(update={"confidence": max(0.0, lesson.confidence - cfg.confidence_step)}), cfg
    )


def retire_if_weak(lesson: Lesson, cfg: MemoryConfig) -> Lesson:
    if lesson.status == "ACTIVE" and lesson.confidence < cfg.retire_below_confidence:
        return lesson.model_copy(update={"status": "RETIRED"})
    return lesson
