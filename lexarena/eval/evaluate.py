"""Evaluate a finished run against the sealed ground truth (CLAUDE.md §9.2).

  python -m lexarena.cli evaluate --run-id dev1 --split dev

Reads runs/<run_id>/<case>/verdict.json (bench), baseline.json (single-LLM baseline, if run) and transcript.json;
ground truth only from public_db (the evaluator is the only reader). Writes runs/<run_id>/metrics.json and
metrics.md. Issue-level alignment (LLM-graded) is not implemented yet.
"""
import json
from pathlib import Path

from lexarena.config import Settings
from lexarena.eval.ground_truth import load_ground_truth
from lexarena.eval.metrics import (binary_metrics, bootstrap_ci, flag_stats, majority_predictor, mcnemar,
                                   metadata_predictor)
from lexarena.public_db import UnspoiledStore


def _read(path: Path) -> dict | None:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def evaluate(settings: Settings, run_id: str, split: str) -> dict:
    store = UnspoiledStore(settings.public_db_dir)
    gold = load_ground_truth(settings.public_db_dir)
    cases = store.split(split)
    try:
        train_ids = store.split("train")
    except FileNotFoundError:
        train_ids = []
    train = [(store.get(u).proceeding_type, store.get(u).appellant_role, gold[u]["appellant_won"])
             for u in train_ids if u in gold and gold[u]["appellant_won"] is not None]
    majority = majority_predictor([w for _, _, w in train])
    metadata = metadata_predictor(train)

    run_dir = settings.runs_dir / run_id
    rows, transcripts, missing = [], [], []
    for uid in cases:
        g = gold.get(uid)
        if g is None or g["appellant_won"] is None:
            continue
        case = store.get(uid)
        meta = {"proceeding_type": case.proceeding_type, "appellant_role": case.appellant_role}
        verdict, base, tr = (_read(run_dir / uid / f) for f in ("verdict.json", "baseline.json", "transcript.json"))
        if tr:
            transcripts.append(tr)
        if verdict is None:
            missing.append(uid)
        rows.append({"case_uid": uid, "gold": g["appellant_won"], "gold_label": g["label"], **meta,
                     "system": verdict["appellant_won"] if verdict else None,
                     "system_label": verdict["label"] if verdict else None,
                     "single_llm": base["prediction"]["appellant_won"] if base else None,
                     "majority": majority(meta), "metadata": metadata(meta)})

    def score(key: str) -> dict:
        pairs = [(r[key], r["gold"]) for r in rows if r[key] is not None]
        m = binary_metrics(pairs)
        if pairs:
            ci = bootstrap_ci(pairs)
            m["balanced_accuracy_ci95"] = list(ci) if ci else None
        return m

    systems = {k: score(k) for k in ("system", "single_llm", "majority", "metadata")}
    both = [r for r in rows if r["system"] is not None and r["single_llm"] is not None]
    paired = mcnemar([r["system"] for r in both], [r["single_llm"] for r in both], [r["gold"] for r in both]) if both else None
    by_type: dict[str, list] = {}
    for r in rows:
        if r["system"] is not None:
            by_type.setdefault(r["proceeding_type"], []).append((r["system"], r["gold"]))
    result = {
        "run_id": run_id, "split": split, "cases_in_split": len(cases), "cases_scored": len(rows),
        "verdicts_missing": missing, "train_cases_for_baselines": len(train),
        "outcome": systems, "system_vs_single_llm": paired,
        "by_proceeding_type": {k: binary_metrics(v) for k, v in sorted(by_type.items())},
        "label_exact_match": (sum(r["system_label"] == r["gold_label"] for r in rows if r["system_label"])
                              / max(1, sum(1 for r in rows if r["system_label"]))),
        "themis_flags": flag_stats(transcripts),
        "notes": ["Silver cases are for development only; never report silver numbers as results (CLAUDE.md §6.6.4a).",
                  "Issue-level alignment (LLM-graded, lawyer-checked) not implemented yet."],
        "rows": rows,
    }
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "metrics.json").write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    (run_dir / "metrics.md").write_text(render(result), encoding="utf-8")
    return result


def render(r: dict) -> str:
    lines = [f"# Evaluation: run {r['run_id']} ({r['split']})", "",
             f"Cases scored: {r['cases_scored']} of {r['cases_in_split']}; verdicts missing: {len(r['verdicts_missing'])}.", "",
             "| System | n | Accuracy | Balanced acc. (95% CI) | Macro-F1 |", "|---|---|---|---|---|"]
    for name, m in r["outcome"].items():
        if not m.get("n"):
            lines.append(f"| {name} | 0 | – | – | – |")
            continue
        ci = m.get("balanced_accuracy_ci95")
        ci_s = f" ({ci[0]:.2f}–{ci[1]:.2f})" if ci else ""
        lines.append(f"| {name} | {m['n']} | {m['accuracy']:.3f} | {m['balanced_accuracy']:.3f}{ci_s} | {m['macro_f1']:.3f} |")
    if r["system_vs_single_llm"]:
        p = r["system_vs_single_llm"]
        lines += ["", f"System vs single-LLM (McNemar, same cases): system-only correct {p['a_only_correct']}, "
                      f"baseline-only correct {p['b_only_correct']}, p = {p['p_value']:.3f}."]
    lines += ["", "## THEMIS flags per side", "", "```json", json.dumps(r["themis_flags"], indent=1), "```", ""]
    lines += [f"- {n}" for n in r["notes"]]
    return "\n".join(lines) + "\n"
