"""THEMIS-LOCAL layer 1: claim extraction (BUILD_PLAN Step 7; SPEC D1; D-062).

The verifier model (a different family from the lawyers, temperature 0) reads one argument and fills, for each
offered statute the argument relies on, a checklist with the same keys as the Law DB entry. Code then holds the
extraction to the argument, so an extraction error can never reject a good argument:
- a checklist for a statute that was not offered is dropped and reported;
- a quote that is not found verbatim in the argument (whitespace and case aside) gets confidence 0, so the audit
  treats it as UNMAPPED;
- a reading not among a predicate's options is dropped;
- an amount ID not in the record is dropped (the audit then reports UNMAPPED);
- every claim that can cause a hard error (a stated minimum amount, "the minimum is met", a stated period) needs the
  argument's own words: the quote must be verbatim in the argument and, for a number, contain that number (digits,
  or digits with an Indian numbering word from config, such as "1 crore"). Otherwise the claim is dropped and
  reported UNMAPPED (D-066). A number written only in words is therefore never checked: a missed check, not a
  rejection.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from fractions import Fraction

from lexarena.llm.client import LLMClient
from lexarena.prompts import PromptStore
from lexarena.schemas.case import Amount
from lexarena.schemas.config import AppConfig
from lexarena.schemas.law import LIST_FIELDS
from lexarena.schemas.predicate import PredicateEntry
from lexarena.schemas.themis import ArgumentExtraction, ChecklistDraft
from lexarena.schemas.transcript import ClaimedItem, ExtractedChecklist, ThemisWarning
from lexarena.storage.temporal import StatuteView

ROLE = "verifier"
UNMAPPED = "UNMAPPED"
NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")
WORD = re.compile(r"[a-z]+")


@dataclass
class ExtractionReport:
    checklists: list[ExtractedChecklist]
    notes: list[str] = field(default_factory=list)
    # Claims dropped because the argument's words do not support them; the caller adds these to layer 1's warnings.
    warnings: list[ThemisWarning] = field(default_factory=list)


def _squeeze(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().casefold()


def render_statute(view: StatuteView, predicates: list[PredicateEntry]) -> str:
    record = view.record
    lines = [f"[{view.statute_id}] {record.act_name}, {record.section_number}: {record.section_title}"]
    for name in LIST_FIELDS:
        items: list[str] = getattr(record.diagnostic_checklist, name)
        if items:
            lines.append(f"  {name}:")
            lines += [f"    {i}. {text}" for i, text in enumerate(items)]
    for p in predicates:
        for param in p.open_parameters:
            lines.append(f"  reading {param.name}: one of {', '.join(param.options)} ({param.note})")
    return "\n".join(lines)


def render_amounts(amounts: dict[str, Amount]) -> str:
    return "\n".join(f"- {a.amount_id}: {a.label}, INR {a.value_inr}" for a in amounts.values()) or "(none)"


def unit_words(cfg: AppConfig) -> dict[str, int]:
    return {u.word.casefold(): u.value for u in cfg.themis_local.amount_unit_words}


def numbers_in(quote: str, unit_words: dict[str, int]) -> set[Fraction]:
    """The numbers a quote states: its digit groups (Indian commas allowed), and each scaled by any numbering word."""
    found = {Fraction(m.group(0).replace(",", "")) for m in NUMBER.finditer(quote)}
    words = set(WORD.findall(quote.casefold()))
    return found | {n * scale for n in found for word, scale in unit_words.items() if word in words}


def _supported(quote: str | None, argument: str, value: float | None, unit_words: dict[str, int]) -> bool:
    if not quote or not quote.strip() or _squeeze(quote) not in argument:
        return False
    return value is None or Fraction(value) in numbers_in(quote, unit_words)


def _ground(draft: ChecklistDraft, argument: str, unit_words: dict[str, int], out: ExtractionReport) -> ChecklistDraft:
    """Drop every hard-error-capable claim the argument's own words do not state."""
    dropped: list[str] = []
    threshold = draft.diagnostic_checklist.financial_threshold
    if threshold.minimum_amount is not None and not _supported(
        draft.minimum_amount_quote, argument, threshold.minimum_amount, unit_words
    ):
        threshold = threshold.model_copy(update={"minimum_amount": None})
        dropped.append("financial_threshold")
    met, amount_id = draft.asserts_threshold_met, draft.threshold_amount_id
    if met is not None and not _supported(draft.threshold_met_quote, argument, None, unit_words):
        met, amount_id = None, None
        dropped.append("asserts_threshold_met")
    timelines = draft.procedural_timelines.model_copy()
    for key, quote in (
        ("adjudication_window_days", draft.adjudication_window_quote),
        ("rectification_window_days", draft.rectification_window_quote),
    ):
        value = getattr(timelines, key)
        if value is not None and not _supported(quote, argument, value, unit_words):
            setattr(timelines, key, None)
            dropped.append(key)
    for name in dropped:
        out.warnings.append(
            ThemisWarning(
                code=UNMAPPED, field=name, detail=f"{draft.statute_id}: not stated in the argument's quoted words"
            )
        )
    return draft.model_copy(
        update={
            "diagnostic_checklist": draft.diagnostic_checklist.model_copy(update={"financial_threshold": threshold}),
            "asserts_threshold_met": met,
            "threshold_amount_id": amount_id,
            "procedural_timelines": timelines,
        }
    )


def _hold_to_argument(item: ClaimedItem, argument: str) -> ClaimedItem:
    if item.quote.strip() and _squeeze(item.quote) in argument:
        return item
    return item.model_copy(update={"confidence": 0.0})


def _clean(
    checklist: ExtractedChecklist,
    argument: str,
    options: dict[str, set[str]],
    notes: list[str],
) -> ExtractedChecklist:
    lists = {
        name: [_hold_to_argument(i, argument) for i in getattr(checklist.diagnostic_checklist, name)]
        for name in LIST_FIELDS
    }
    unquoted = sum(
        1
        for name in LIST_FIELDS
        for before, after in zip(getattr(checklist.diagnostic_checklist, name), lists[name], strict=True)
        if before.confidence != after.confidence
    )
    if unquoted:
        notes.append(f"{checklist.statute_id}: {unquoted} item(s) quoted words not in the argument")
    readings = {k: v for k, v in checklist.chosen_readings.items() if v in options.get(k, set())}
    if readings != checklist.chosen_readings:
        notes.append(f"{checklist.statute_id}: dropped unknown readings {checklist.chosen_readings}")
    return checklist.model_copy(
        update={
            "diagnostic_checklist": checklist.diagnostic_checklist.model_copy(update=lists),
            "chosen_readings": readings,
        }
    )


def extract_checklists(
    llm: LLMClient,
    prompts: PromptStore,
    cfg: AppConfig,
    argument: str,
    views: dict[str, StatuteView],
    predicates: dict[str, list[PredicateEntry]],
    amounts: dict[str, Amount],
    *,
    session_id: str,
) -> ExtractionReport:
    if not views:
        return ExtractionReport([], ["no statutes to extract against"])
    ref = cfg.prompts.themis_extract
    statutes = "\n\n".join(render_statute(v, predicates.get(sid, [])) for sid, v in views.items())
    prompt = prompts.render(ref.id, ref.version, statutes=statutes, amounts=render_amounts(amounts), argument=argument)
    raw = llm.complete_json(role=ROLE, user=prompt, schema=ArgumentExtraction, session_id=session_id).value
    squeezed = _squeeze(argument)
    report = ExtractionReport([])
    notes = report.notes
    for draft in raw.checklists:
        if draft.threshold_amount_id is not None and draft.threshold_amount_id not in amounts:
            notes.append(f"{draft.statute_id}: dropped unknown amount {draft.threshold_amount_id}")
        if draft.statute_id not in views:
            notes.append(f"dropped a checklist for {draft.statute_id}, which was not offered")
            continue
        checklist = _ground(draft, squeezed, unit_words(cfg), report).to_checklist(set(amounts))
        options = {
            param.name: set(param.options)
            for p in predicates.get(checklist.statute_id, [])
            for param in p.open_parameters
        }
        report.checklists.append(_clean(checklist, squeezed, options, notes))
    return report
