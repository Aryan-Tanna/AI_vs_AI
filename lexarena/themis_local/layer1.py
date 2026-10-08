"""THEMIS-LOCAL layer 1 over one argument (BUILD_PLAN Step 7; SPEC D1, D2, D3, D8; D-062, D-063).

For each statute checklist extracted from the argument:
1. the statute must be visible on the case dates; otherwise STATUTE_NOT_AVAILABLE goes to layer 2 (whether the
   citation itself is real is layer 2's question);
2. the D1 audit (audit.py);
3. every APPROVED, current predicate for that statute, with claim inputs read from the checklist and the reading
   the argument chose for each open parameter; a skipped predicate is UNMAPPED;
4. for a statute carrying an approved limitation-period overlay value (the data marks it; no statute ID in code or
   config), the date chain from approved overlay values, as a warning only (D-063): limitation
   turns on dates of default and acknowledgments that are usually contested, and it is not a SPEC D8 hard error.

A stated value the extractor attached to several statutes (measured: one sentence about s.7's period copied onto
s.21) is ambiguous about which statute counsel meant; it is a misstatement only if it matches none of them, so a value
that is right for one of them never rejects the argument. Only a statute whose law actually holds that value excuses
it; a statute with no value cannot.

Hard errors are deduplicated by (code, statute), keeping the first detail, so retry feedback names each problem once.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from lexarena.schemas.case import Amount
from lexarena.schemas.config import ThemisLocalConfig
from lexarena.schemas.predicate import PredicateEntry
from lexarena.schemas.transcript import ExtractedChecklist, ThemisWarning
from lexarena.storage.temporal import StatuteView
from lexarena.themis_local.audit import UNMAPPED, HardError, audit_statute
from lexarena.themis_local.limitation import limitation_expiry, rule_from_overlays
from lexarena.themis_local.predicates import evaluate, resolve_inputs, select_approved

STATUTE_NOT_AVAILABLE = "STATUTE_NOT_AVAILABLE"
WARN_LIMITATION_INCONSISTENT = "WARN_LIMITATION_INCONSISTENT"


@dataclass(frozen=True)
class CaseFacts:
    """The record values layer 1 may compare against: agent-visible amounts and key dates only."""

    amounts: dict[str, Amount]
    key_dates: dict[str, date]
    date_fact_ids: dict[str, str]


@dataclass
class Layer1Result:
    hard_errors: list[HardError] = field(default_factory=list)
    warnings: list[ThemisWarning] = field(default_factory=list)
    predicates_run: list[str] = field(default_factory=list)
    predicates_failed: list[str] = field(default_factory=list)


def _record_ids(predicate: PredicateEntry, facts: CaseFacts) -> list[str]:
    ids: list[str] = []
    for item in predicate.inputs:
        kind, _, key = item.source.partition(":")
        if kind == "record.amounts":
            ids += [a.amount_id for a in facts.amounts.values() if a.label == key]
        elif kind == "record.key_dates" and key in facts.date_fact_ids:
            ids.append(facts.date_fact_ids[key])
    return ids


def _run_predicates(
    view: StatuteView,
    checklist: ExtractedChecklist,
    predicates: list[PredicateEntry],
    facts: CaseFacts,
    out: Layer1Result,
) -> None:
    law = view.record.to_document()
    dated = {a.parameter: a.value for a in view.applied}
    claim = checklist.model_dump(mode="python")
    by_label = {a.label: a.value_inr for a in facts.amounts.values()}
    for predicate in select_approved(predicates, {view.statute_id: view.record}):
        out.predicates_run.append(predicate.predicate_id)
        inputs = resolve_inputs(
            predicate, amounts=by_label, key_dates=facts.key_dates, law=law, overlay=dated, claim=claim
        )
        result = evaluate(predicate, inputs, checklist.chosen_readings)
        if result.status == "FAIL":
            out.predicates_failed.append(predicate.predicate_id)
            out.hard_errors.append(
                HardError(
                    result.error_code or predicate.error_code,
                    view.statute_id,
                    f"predicate {predicate.predicate_id} ({predicate.field}) does not hold for the stated claim",
                    _record_ids(predicate, facts),
                )
            )
        elif result.status == "SKIPPED":
            out.warnings.append(
                ThemisWarning(
                    code=UNMAPPED,
                    field=predicate.field,
                    detail=f"predicate {predicate.predicate_id} not checked; missing {', '.join(result.missing)}",
                )
            )


def _check_limitation(
    view: StatuteView, checklist: ExtractedChecklist, facts: CaseFacts, cfg: ThemisLocalConfig, out: Layer1Result
) -> None:
    lim = cfg.limitation
    if checklist.asserts_within_limitation is None:
        return
    rule = rule_from_overlays(
        view.applied,
        period=lim.period_parameter,
        excluded=lim.excluded_parameter,
        minimum=lim.minimum_balance_parameter,
    )
    default, filed = facts.key_dates.get(lim.default_date_label), facts.key_dates.get(lim.filing_date_label)
    if rule is None or default is None or filed is None:
        return
    result = limitation_expiry(default, checklist.acknowledgment_dates, rule)
    if result.needs_review:
        out.warnings.append(
            ThemisWarning(code=UNMAPPED, field="limitation", detail="acknowledgment inside an excluded window")
        )
    elif (filed <= result.expiry) != checklist.asserts_within_limitation:
        out.warnings.append(
            ThemisWarning(
                code=WARN_LIMITATION_INCONSISTENT,
                field="limitation",
                detail=f"on the stated dates the period runs to {result.expiry.isoformat()}; filed {filed.isoformat()}",
            )
        )


def _dedupe(errors: list[HardError]) -> list[HardError]:
    seen: dict[tuple[str, str], HardError] = {}
    for error in errors:
        kept = seen.setdefault((error.code, error.statute_id), error)
        if kept is not error:
            kept.record_ids = sorted(set(kept.record_ids) | set(error.record_ids))
    return list(seen.values())


def run_layer1(
    checklists: list[ExtractedChecklist],
    views: dict[str, StatuteView],
    predicates: dict[str, list[PredicateEntry]],
    facts: CaseFacts,
    cfg: ThemisLocalConfig,
) -> Layer1Result:
    out = Layer1Result()
    matched: set[tuple[str, float]] = set()
    for checklist in checklists:
        view = views.get(checklist.statute_id)
        if view is None:
            out.warnings.append(
                ThemisWarning(code=STATUTE_NOT_AVAILABLE, detail=f"{checklist.statute_id} not checkable by layer 1")
            )
            continue
        audit = audit_statute(view, checklist, facts.amounts, cfg)
        out.hard_errors += audit.hard_errors
        out.warnings += audit.warnings
        matched |= audit.matched
        _run_predicates(view, checklist, predicates.get(view.statute_id, []), facts, out)
        _check_limitation(view, checklist, facts, cfg, out)
    out.hard_errors = _dedupe([e for e in out.hard_errors if e.claim_key is None or e.claim_key not in matched])
    return out
