"""THEMIS-LOCAL layer 1: claim extraction (BUILD_PLAN Step 7; SPEC D1; D-062).

The verifier model (a different family from the lawyers, temperature 0) reads one argument and fills, for each
offered statute the argument relies on, a checklist with the same keys as the Law DB entry. Code then holds the
extraction to the argument, so an extraction error can never reject a good argument:
- a checklist for a statute that was not offered is dropped and reported;
- a quote that is not found verbatim in the argument (whitespace and case aside) gets confidence 0, so the audit
  treats it as UNMAPPED;
- a reading not among a predicate's options is dropped;
- an amount ID not in the record is dropped (the audit then reports UNMAPPED).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from lexarena.llm.client import LLMClient
from lexarena.prompts import PromptStore
from lexarena.schemas.case import Amount
from lexarena.schemas.config import AppConfig
from lexarena.schemas.law import LIST_FIELDS
from lexarena.schemas.predicate import PredicateEntry
from lexarena.schemas.themis import ArgumentExtraction
from lexarena.schemas.transcript import ClaimedItem, ExtractedChecklist
from lexarena.storage.temporal import StatuteView

ROLE = "verifier"


@dataclass
class ExtractionReport:
    checklists: list[ExtractedChecklist]
    notes: list[str] = field(default_factory=list)


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
    notes: list[str] = []
    kept: list[ExtractedChecklist] = []
    for draft in raw.checklists:
        if draft.threshold_amount_id is not None and draft.threshold_amount_id not in amounts:
            notes.append(f"{draft.statute_id}: dropped unknown amount {draft.threshold_amount_id}")
        checklist = draft.to_checklist(set(amounts))
        if checklist.statute_id not in views:
            notes.append(f"dropped a checklist for {checklist.statute_id}, which was not offered")
            continue
        options = {
            param.name: set(param.options)
            for p in predicates.get(checklist.statute_id, [])
            for param in p.open_parameters
        }
        kept.append(_clean(checklist, squeezed, options, notes))
    return ExtractionReport(kept, notes)
