"""Check that a clerked case is split correctly between what agents see and what stays sealed. Read-only.

For each case (only before its first session: the REVIEW window, D-056):
1. routing: how many judgment paragraphs went to each part; agent-visible parts are FACTS, LOWER_ORDER, ISSUES,
   SUBMISSIONS_P and SUBMISSIONS_R, sealed parts are ANALYSIS and CONCLUSION (HEADER is pseudonymised);
2. source paragraphs: every agent-view item cites agent-visible paragraphs, or single sentences of sealed paragraphs
   that only restate the record (D-058); each such sentence is printed so a person can confirm it is not a finding;
3. verbatim leakage: any run of SHINGLE words from a sealed paragraph, or from the sealed findings and conclusion,
   that appears in the agent view;
4. outcome words in the agent view (shown with context; describing the lower forum's order is allowed);
5. balance: each contested fact has both versions, each framed issue is a question, each side has a pleaded ground
   on each issue;
6. precedent exclusions recorded by the clerk.

    .venv/Scripts/python scripts/check_split.py DEV_0005 [DEV_0006 ...]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from typing import Any

from lexarena.app import DEFAULT_ENV_FILE, SEALED_ENV_FILE
from lexarena.clerk.steps import split_sentences
from lexarena.schemas.judgment import AGENT_VISIBLE_PARTS
from lexarena.storage.factory import SealedProcess

SHINGLE = 8  # literal-ok: words per verbatim-overlap window (a report setting, not law or tuning)
OUTCOME = re.compile(
    r"(?i)\b(appeal (is|stands|be) (allowed|dismissed)|is hereby|we (hold|find|are of the (view|opinion))|"
    r"this (tribunal|court|bench) (holds|finds|is of)|set aside|upheld|accordingly|in the result|"
    r"stands dismissed|stands allowed|deserves to be|no merit)\b"
)


def words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def shingles(text: str) -> set[tuple[str, ...]]:
    w = words(text)
    return {tuple(w[i : i + SHINGLE]) for i in range(len(w) - SHINGLE + 1)}


def where(run: tuple[str, ...], av: Any) -> str:
    """The agent-view field whose text contains the run, with that text."""
    needle = " ".join(run)

    def walk(node: Any, path: str) -> str | None:
        if isinstance(node, str):
            return f"{path}: {node[:220]}" if needle in " ".join(words(node)) else None
        items = node.items() if isinstance(node, dict) else enumerate(node) if isinstance(node, list) else []
        for k, v in items:
            found = walk(v, f"{path}.{k}")
            if found:
                return found
        return None

    return walk(av.model_dump(mode="json"), "agent_view") or "(spans fields)"


def items_with_sources(av: Any) -> list[tuple[str, list[str]]]:
    r = av.record
    out: list[tuple[str, list[str]]] = []
    out += [(f.fact_id, list(f.source_paras)) for f in r.stipulated_facts]
    out += [(c.fact_id, list(c.source_paras)) for c in r.contested_facts]
    out += [(e.exhibit_id, list(e.source_paras)) for e in r.exhibits]
    for side in ("PETITIONER", "RESPONDENT"):
        out += [(f"ground {side[0]} {g.issue_id}", list(g.source_paras)) for g in av.opening_positions.for_side(side)]
    return out


def check(proc: SealedProcess, case_id: str) -> list[str]:
    review = proc.review()
    case = review.cases.get(case_id)
    av = case.agent_view
    truth = review.ground_truth.get_for_review(case_id)
    text = review.judgment_texts.get_for_review(case_id)
    lines = [f"# {case_id}", ""]

    parts = Counter(p.part for p in text.paragraphs)
    lines.append(f"routing: {dict(parts)}")
    part_of = {p.para_id: p.part for p in text.paragraphs}
    unrouted = [p.para_id for p in text.paragraphs if p.part is None]
    if unrouted:
        lines.append(f"  WARN unrouted paragraphs: {unrouted}")

    text_of = {p.para_id: p.text for p in text.paragraphs}
    bad_src: list[str] = []
    sentences: dict[str, str] = {}
    for item, paras in items_with_sources(av):
        for ref in paras:
            para, _, sent = re.sub(r"\(.*\)$", "", ref).partition(".S")
            part = part_of.get(para)
            if part in AGENT_VISIBLE_PARTS:
                continue
            if not sent:
                bad_src.append(f"{item} cites the whole sealed paragraph {para} ({part})")
                continue
            split = split_sentences(text_of.get(para, ""))
            n = int(sent)
            sentences[ref] = split[n - 1] if 0 < n <= len(split) else "(sentence not found)"
    lines.append(f"source paragraphs: {'OK' if not bad_src else 'PROBLEM'}")
    lines += [f"  {b}" for b in bad_src]
    lines.append(
        f"record-fact sentences from sealed paragraphs (D-058; confirm each is fact, not finding): {len(sentences)}"
    )
    lines += [f"  [{k}] {v}" for k, v in sorted(sentences.items())]

    view_text = json.dumps(av.model_dump(mode="json"), ensure_ascii=False)
    view_sh = shingles(view_text)
    sealed_texts = [(p.para_id, p.text) for p in text.paragraphs if p.part in ("ANALYSIS", "CONCLUSION")]
    sealed_texts += [(f"finding {f.issue_id}", f"{f.finding} {f.reasoning}") for f in truth.issue_findings]
    sealed_texts += [("conclusion", " ".join(r.relief for r in truth.conclusion.reliefs))]
    leaks = []
    for src, t in sealed_texts:
        hit = shingles(t) & view_sh
        if hit:
            leaks.append(f"{src}: {len(hit)} shared {SHINGLE}-word runs")
            if not src.startswith("P"):  # a sealed finding or conclusion: show where the words sit in the agent view
                for run in sorted(hit)[:: max(1, len(hit) // 3)][:3]:
                    leaks.append(f"    '{' '.join(run)}' in: {where(run, av)}")
    lines.append(f"verbatim overlap with sealed text: {'NONE' if not leaks else 'FOUND (inspect)'}")
    lines += [f"  {x}" for x in leaks]

    hits = [m for m in OUTCOME.finditer(view_text)]
    lines.append(f"outcome words in agent view: {len(hits)}")
    lines += [f"  ...{view_text[max(0, m.start() - 120) : m.end() + 60]}..." for m in hits]

    problems = []
    for c in av.record.contested_facts:
        if not c.petitioner_version.strip() or not c.respondent_version.strip():
            problems.append(f"{c.fact_id} lacks a side's version")
    for i in av.framed_issues:
        q = i.question.strip()
        if not (q.endswith("?") or q.lower().startswith("whether")):
            problems.append(f"issue {i.issue_id} is not phrased as a question")
        for side in ("PETITIONER", "RESPONDENT"):
            if not any(g.issue_id == i.issue_id for g in av.opening_positions.for_side(side)):
                problems.append(f"no {side} ground on {i.issue_id}")
    lines.append(f"balance: {'OK' if not problems else 'PROBLEM'}")
    lines += [f"  {p}" for p in problems]
    lines.append(
        f"record: {len(av.record.stipulated_facts)} stipulated, {len(av.record.contested_facts)} contested, "
        f"{len(av.record.exhibits)} exhibits, {len(av.record.amounts)} amounts; issues {len(av.framed_issues)}"
    )
    lines.append(f"excluded precedents: {case.build.excluded_precedent_ids}")
    lines.append(f"clerk flags: {[f.code for f in case.build.extraction_flags]}")
    lines.append(f"memorization probe: {case.build.memorization_probe}")
    return lines


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("case_ids", nargs="+")
    args = ap.parse_args()
    proc = SealedProcess.from_env_files([DEFAULT_ENV_FILE, SEALED_ENV_FILE])
    for cid in args.case_ids:
        try:
            print("\n".join(check(proc, cid)), end="\n\n")
        except Exception as exc:  # report and continue with the next case
            print(f"# {cid}\n  cannot check: {exc}\n", file=sys.stderr)


if __name__ == "__main__":
    main()
