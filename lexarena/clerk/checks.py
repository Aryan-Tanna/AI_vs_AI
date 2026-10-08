"""Deterministic verification of a clerked case (BUILD_PLAN Step 6; SPEC H5, I3-8; D-056).

- `literal_problems`: every key date and every amount must be written in the source text of the fact it cites
  (dates in any common form; amounts with lakh and crore read exactly). A value the text does not state is never
  accepted: it blocks the case.
- `leakage_problems`: the finished agent view must carry no case number, no bench member's name, no decision date,
  no real name, no case citation or pleaded authority, no court voice, no evaluative word in an issue (SPEC A3),
  and no run of words copied from the tribunal's reasoning that does not also occur in agent-visible text.
- `grounds_balance`: both sides' opening grounds should be comparable (non-negotiable 3); a large gap is flagged.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from datetime import date
from decimal import Decimal

from lexarena.clerk.names import residual_names
from lexarena.clerk.scan import citation_hits, court_voice_hits
from lexarena.schemas.case import AgentView, ExtractionFlag
from lexarena.schemas.clerk import NamedEntity

MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
          "november", "december"]  # fmt: skip
SHOWN = 5  # literal-ok: examples quoted in a problem message (display only)
MONTH_ABBREV = 3  # literal-ok: "Jun" for June, the common abbreviation length
LAKH, CRORE = Decimal(100_000), Decimal(10_000_000)  # literal-ok: Indian numbering units, not legal values
AMOUNT = re.compile(r"(?P<num>\d[\d,]*(?:\.\d+)?)\s*(?:/-)?\s*(?P<unit>crores?|cr\b|lakhs?|lacs?|lakh)?", re.IGNORECASE)


# ---------------------------------------------------------------- literal values


def _date_forms(d: date) -> list[re.Pattern[str]]:
    month = MONTHS[d.month - 1]
    day = rf"0?{d.day}(?:st|nd|rd|th)?"
    num = rf"(?<!\d)0?{d.day}\s*[./-]\s*0?{d.month}\s*[./-]\s*{d.year}(?!\d)"
    words = rf"(?<!\d){day}\s+(?:of\s+)?{month[:MONTH_ABBREV]}[a-z]*\.?,?\s+{d.year}"
    us = rf"{month[:MONTH_ABBREV]}[a-z]*\.?\s+{day},?\s+{d.year}"
    return [re.compile(p, re.IGNORECASE) for p in (num, words, us, re.escape(d.isoformat()))]


def date_written_in(d: date, text: str) -> bool:
    return any(p.search(text) for p in _date_forms(d))


def amounts_in(text: str) -> set[int]:
    found: set[int] = set()
    for m in AMOUNT.finditer(text):
        raw = m["num"].replace(",", "")
        if not raw.replace(".", "").isdigit():
            continue
        value = Decimal(raw)
        unit = (m["unit"] or "").lower()
        if unit.startswith("cr"):
            value *= CRORE
        elif unit.startswith(("lakh", "lac")):
            value *= LAKH
        found.add(int(value))
    return found


def literal_problems(view: AgentView, sources: dict[str, str]) -> list[str]:
    """`sources` maps each source ID (P3, P4.S1) to its pseudonymised text."""
    r = view.record
    fact_sources = {f.fact_id: f.source_paras for f in r.stipulated_facts}
    fact_sources |= {c.fact_id: c.source_paras for c in r.contested_facts}

    def text_of(fact_id: str) -> str:
        return " ".join(sources.get(s, "") for s in fact_sources.get(fact_id, []))

    problems = [
        f"key date {kd.label} {kd.date.isoformat()} is not written in the sources of {kd.fact_id}"
        for kd in view.metadata.key_dates
        if not date_written_in(kd.date, text_of(kd.fact_id))
    ]
    for a in r.amounts:
        text = text_of(a.fact_id)
        if int(a.value_inr) not in amounts_in(text):
            problems.append(f"amount {a.amount_id} ({a.value_inr}) is not written in the sources of {a.fact_id}")
        if a.date is not None and not date_written_in(a.date, text):
            problems.append(
                f"amount {a.amount_id} date {a.date.isoformat()} is not written in the sources of {a.fact_id}"
            )
    return problems


# ---------------------------------------------------------------- leakage


def _words(text: str) -> list[str]:
    """Words without numbers: a date or figure written another way must not make or break a match."""
    return re.findall(r"[a-z]+", text.lower())


def _ngrams(texts: Iterable[str], n: int) -> set[tuple[str, ...]]:
    out: set[tuple[str, ...]] = set()
    for t in texts:
        w = _words(t)
        out |= {tuple(w[i : i + n]) for i in range(len(w) - n + 1)}
    return out


def reasoning_overlap(text: str, reasoning: list[str], visible: list[str], n: int) -> list[str]:
    """Runs of n words shared with the reasoning that do not also occur in agent-visible text."""
    leaked = (_ngrams([text], n) & _ngrams(reasoning, n)) - _ngrams(visible, n)
    return sorted(" ".join(g) for g in leaked)


def leakage_problems(
    view: AgentView,
    *,
    case_number: str,
    bench: list[str],
    decision_date: date,
    entities: list[NamedEntity],
    authority_names: list[str],
    reasoning: list[str],
    visible: list[str],
    cfg_markers: list[str],
    evaluative_words: list[str],
    generic_words: list[str],
    ngram: int,
) -> list[str]:
    shown = view.model_dump(mode="json", exclude={"metadata": {"simulation_date"}})
    text = json.dumps(shown, ensure_ascii=False)
    problems: list[str] = []
    if case_number and re.sub(r"\s+", " ", case_number).lower() in re.sub(r"\s+", " ", text).lower():
        problems.append("the case number appears in the agent view")
    members = [NamedEntity(name=b, variants=[], kind="PERSON", cause_title_role=None) for b in bench]
    if hits := residual_names(text, members, generic_words):
        problems.append(f"bench member names appear in the agent view: {hits}")
    if date_written_in(decision_date, text):
        problems.append("the decision date appears in the agent view")
    if hits := residual_names(text, entities, generic_words):
        problems.append(f"real names appear in the agent view: {hits}")
    if hits := citation_hits(text, authority_names):
        problems.append(f"case citations or pleaded authorities appear in the agent view: {hits[:SHOWN]}")
    if hits := court_voice_hits(text, cfg_markers):
        problems.append(f"the tribunal's own voice appears in the agent view: {hits}")
    for issue in view.framed_issues:
        words = [w for w in evaluative_words if re.search(rf"\b{re.escape(w)}\b", issue.question, re.IGNORECASE)]
        if words:
            problems.append(f"issue {issue.issue_id} uses evaluative words {words} (SPEC A3)")
    if leaked := reasoning_overlap(text, reasoning, visible, ngram):
        problems.append(f"{len(leaked)} run(s) of {ngram} words copied from the reasoning: {leaked[:SHOWN]}")
    return problems


def grounds_balance(view: AgentView, max_ratio: float) -> ExtractionFlag | None:
    """Flag when one side's opening grounds outnumber or outweigh the other's by more than `max_ratio`."""
    p, r = view.opening_positions.PETITIONER, view.opening_positions.RESPONDENT
    sizes = {
        "count": (len(p), len(r)),
        "length": (sum(len(g.ground) for g in p), sum(len(g.ground) for g in r)),
    }
    lopsided = {k: v for k, v in sizes.items() if max(v) > max_ratio * max(min(v), 1)}
    if not lopsided:
        return None
    return ExtractionFlag(
        code="OPENING_GROUNDS_UNBALANCED",
        detail=f"petitioner vs respondent opening grounds: {lopsided}",
        resolution="kept as the judgment records them; review whether a side's case is under-stated",
    )
