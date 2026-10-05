"""Outcome metrics, baselines, confidence intervals and THEMIS flag statistics (CLAUDE.md §9.2).

The headline task is binary: did the appellant win (`appellant_won`)? Cases whose ground truth is null
(withdrawn / disposed) are excluded from it. Accuracy is always reported beside the baselines.
"""
import random
from collections import Counter, defaultdict
from collections.abc import Callable


def binary_metrics(pairs: list[tuple[bool, bool]]) -> dict:
    """pairs = [(predicted, gold)]. Positive class = appellant won."""
    n = len(pairs)
    if n == 0:
        return {"n": 0}
    tp = sum(p and g for p, g in pairs)
    tn = sum((not p) and (not g) for p, g in pairs)
    fp = sum(p and (not g) for p, g in pairs)
    fn = sum((not p) and g for p, g in pairs)

    def f1(tp_, fp_, fn_):
        d = 2 * tp_ + fp_ + fn_
        return 2 * tp_ / d if d else 0.0

    tpr = tp / (tp + fn) if tp + fn else 0.0
    tnr = tn / (tn + fp) if tn + fp else 0.0
    return {"n": n, "accuracy": (tp + tn) / n, "balanced_accuracy": (tpr + tnr) / 2,
            "macro_f1": (f1(tp, fp, fn) + f1(tn, fn, fp)) / 2,
            "confusion": {"tp": tp, "tn": tn, "fp": fp, "fn": fn}, "gold_positive_rate": (tp + fn) / n}


def bootstrap_ci(pairs: list[tuple[bool, bool]], metric: str = "balanced_accuracy", n_boot: int = 2000,
                 seed: int = 0, alpha: float = 0.05) -> tuple[float, float] | None:
    if len(pairs) < 2:
        return None
    rng = random.Random(seed)
    vals = sorted(binary_metrics([pairs[rng.randrange(len(pairs))] for _ in pairs])[metric] for _ in range(n_boot))
    return vals[int(alpha / 2 * n_boot)], vals[int((1 - alpha / 2) * n_boot) - 1]


def mcnemar(a: list[bool], b: list[bool], gold: list[bool]) -> dict:
    """Paired comparison of two systems on the same cases (exact two-sided binomial test on discordant pairs)."""
    a_only = sum(x == g and y != g for x, y, g in zip(a, b, gold))
    b_only = sum(y == g and x != g for x, y, g in zip(a, b, gold))
    n, k = a_only + b_only, min(a_only, b_only)
    from math import comb
    p = min(1.0, 2 * sum(comb(n, i) for i in range(k + 1)) / 2 ** n) if n else 1.0
    return {"a_only_correct": a_only, "b_only_correct": b_only, "p_value": p}


def majority_predictor(train_gold: list[bool]) -> Callable[[dict], bool]:
    """Always predicts the majority outcome of the TRAIN split (never the evaluated split: that would peek)."""
    majority = sum(train_gold) > len(train_gold) / 2 if train_gold else False
    return lambda _case: majority


def metadata_predictor(train: list[tuple[str, str, bool]]) -> Callable[[dict], bool]:
    """Majority outcome per (proceeding_type, appellant_role) in TRAIN, falling back to proceeding type, then overall."""
    by_pair, by_type, overall = defaultdict(list), defaultdict(list), []
    for ptype, role, won in train:
        by_pair[(ptype, role)].append(won)
        by_type[ptype].append(won)
        overall.append(won)

    def maj(xs):
        return sum(xs) > len(xs) / 2

    def predict(case: dict) -> bool:
        key = (case["proceeding_type"], case["appellant_role"])
        if len(by_pair.get(key, [])) >= 3:
            return maj(by_pair[key])
        if len(by_type.get(case["proceeding_type"], [])) >= 3:
            return maj(by_type[case["proceeding_type"]])
        return maj(overall) if overall else False

    return predict


def flag_stats(transcripts: list[dict]) -> dict:
    """THEMIS-LOCAL flags in published turns, per side: counts by code and rates per turn."""
    per_side = defaultdict(lambda: {"turns": 0, "codes": Counter(), "statuses": Counter()})
    for tr in transcripts:
        for t in tr.get("turns", []):
            s = per_side[t["speaker"]]
            s["turns"] += 1
            s["statuses"][t.get("themis", {}).get("status", "NOT_RUN")] += 1
            for f in t.get("flags", []):
                s["codes"][f["code"]] += 1
    out = {}
    for side, s in per_side.items():
        n = s["turns"] or 1
        unsupported = s["codes"]["ERR_UNSUPPORTED_BY_RECORD"] + s["codes"]["ERR_UNKNOWN_RECORD_REF"]
        citations = sum(s["codes"][c] for c in ("ERR_UNVERIFIED_AUTHORITY", "ERR_ANACHRONISTIC_AUTHORITY", "ERR_MISATTRIBUTED_RATIO"))
        facts = s["codes"]["ERR_FACT_MISMATCH"] + s["codes"]["ERR_ARITHMETIC"]
        out[side] = {"turns": s["turns"], "codes": dict(s["codes"]), "statuses": dict(s["statuses"]),
                     "unsupported_fact_rate": round(unsupported / n, 3), "bad_citation_rate": round(citations / n, 3),
                     "fact_error_rate": round(facts / n, 3)}
    return out
