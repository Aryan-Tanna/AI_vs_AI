"""Statistics for the evaluation report (BUILD_PLAN Steps 12, 18; SPEC G1, G2; D-049, D-072). Pure Python, seeded.

- `balanced_accuracy`: the mean of per-class recall over the classes that occur in the truth, so a predictor that
  always says the majority side scores 1 / (number of classes), not the majority share.
- `macro_f1`: the unweighted mean of per-class F1 over the given labels.
- `mcnemar_exact`: the exact two-sided McNemar test on the discordant pairs (b: only A right, c: only B right), a
  binomial test with p = 1/2. Exact, because dev and test sets are small and the chi-square approximation is poor.
- `bootstrap_ci`: a percentile interval from resampling cases with replacement; the seed and the number of resamples
  come from config, so the interval is reproducible.
"""

from __future__ import annotations

import random
from collections.abc import Callable, Sequence
from math import comb
from typing import TypeVar

T = TypeVar("T")
HALF = 0.5  # literal-ok: the null hypothesis of McNemar's test is a fair coin over discordant pairs


def _recall(truth: Sequence[str], pred: Sequence[str], label: str) -> float | None:
    support = [p for t, p in zip(truth, pred, strict=True) if t == label]
    return sum(p == label for p in support) / len(support) if support else None


def balanced_accuracy(truth: Sequence[str], pred: Sequence[str]) -> float | None:
    recalls = [r for label in sorted(set(truth)) if (r := _recall(truth, pred, label)) is not None]
    return sum(recalls) / len(recalls) if recalls else None


def macro_f1(truth: Sequence[str], pred: Sequence[str], labels: Sequence[str]) -> float | None:
    if not truth:
        return None
    scores: list[float] = []
    for label in labels:
        tp = sum(t == label and p == label for t, p in zip(truth, pred, strict=True))
        fp = sum(t != label and p == label for t, p in zip(truth, pred, strict=True))
        fn = sum(t == label and p != label for t, p in zip(truth, pred, strict=True))
        scores.append(0.0 if tp == 0 else (2 * tp) / (2 * tp + fp + fn))  # literal-ok: F1 = 2TP / (2TP + FP + FN)
    return sum(scores) / len(scores) if scores else None


def mcnemar_exact(only_a_right: int, only_b_right: int) -> float:
    """Two-sided exact p-value; 1.0 when there are no discordant pairs."""
    n = only_a_right + only_b_right
    if n == 0:
        return 1.0
    k = min(only_a_right, only_b_right)
    tail = sum(comb(n, i) for i in range(k + 1)) * HALF**n
    return min(1.0, tail + tail)  # two-sided: both tails of a symmetric distribution


def bootstrap_ci(
    items: Sequence[T],
    statistic: Callable[[Sequence[T]], float | None],
    *,
    resamples: int,
    level: float,
    seed: int,
) -> tuple[float, float] | None:
    if not items:
        return None
    rng = random.Random(seed)
    values = sorted(v for _ in range(resamples) if (v := statistic([rng.choice(items) for _ in items])) is not None)
    if not values:
        return None
    alpha = (1 - level) * HALF
    lo = values[min(len(values) - 1, int(alpha * len(values)))]
    hi = values[min(len(values) - 1, int((1 - alpha) * len(values)))]
    return lo, hi
