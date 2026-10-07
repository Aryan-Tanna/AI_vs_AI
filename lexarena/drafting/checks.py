"""Mechanical checks on a drafted item, split into what blocks approval and what the reviewer must judge.

Blocking: a quote that is not verbatim in the registered source; a date that is not written in its quote
(dates are never inferred, e.g. from an assent date when commencement is left to a notification); a label
or parameter outside the configured vocabulary; a value of the wrong shape; a predicate that is not a valid
`PredicateEntry` or points at a Law DB item that does not exist.

Reviewer must judge: numbers written in words; missing commencement dates; and, always, the legal questions
no code can answer (which version of the law applies; whether a rule is fixed literally by the text).
"""

from __future__ import annotations

import json
from datetime import date

from pydantic import ValidationError

from lexarena.drafting.models import Check, ProposedOverlayRow, ProposedPredicate
from lexarena.drafting.sources import dates_mentioned, find_quote, numbers_mentioned
from lexarena.schemas.config import VocabularyConfig
from lexarena.schemas.law import LawRecord, checklist_item, item_hash
from lexarena.schemas.overlay import DECISION_LABEL, IN_FORCE_PARAMETER
from lexarena.schemas.predicate import ConstLeaf, PredicateEntry, walk


class Findings:
    def __init__(self) -> None:
        self.checks: list[Check] = []
        self.blocking: list[str] = []
        self.judge: list[str] = []

    def quote(self, name: str, quote: str | None, source_text: str, required: bool) -> None:
        if not quote:
            self.checks.append(Check(name=name, status="MISSING", detail="no quote given"))
            if required:
                self.blocking.append(f"{name} needs a quote from the source")
            return
        span = find_quote(quote, source_text)
        if span is None:
            self.checks.append(Check(name=name, status="NOT_FOUND", detail=quote))
            self.blocking.append(f"{name}: quote not found verbatim in the source")
        else:
            self.checks.append(Check(name=name, status="VERIFIED", detail=f"chars {span[0]}-{span[1]}"))


def _parse_date(value: str | None, name: str, f: Findings) -> date | None:
    if value is None:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        f.blocking.append(f"{name} {value!r} is not a YYYY-MM-DD date")
        return None


def _date_in_quote(day: date | None, quote: str | None, name: str, f: Findings) -> None:
    if day is None or not quote:
        return
    if day in dates_mentioned(quote):
        f.checks.append(Check(name=f"{name}_date", status="MATCHED", detail=day.isoformat()))
    else:
        f.checks.append(Check(name=f"{name}_date", status="NOT_MATCHED", detail=day.isoformat()))
        f.blocking.append(f"{name} {day.isoformat()} is not written in its quote; dates are never inferred")


def check_overlay_row(row: ProposedOverlayRow, source_text: str, vocab: VocabularyConfig) -> Findings:
    f = Findings()
    if row.parameter not in vocab.overlay_parameters:
        f.blocking.append(f"parameter {row.parameter!r} is not in vocabulary.overlay_parameters")
    if row.keyed_on not in vocab.case_date_labels:
        f.blocking.append(f"keyed_on {row.keyed_on!r} is not in vocabulary.case_date_labels")
    f.quote("source_text", row.source_text, source_text, required=True)
    f.quote("value_quote", row.value_quote, source_text, required=True)

    kind = row.value_kind
    if row.parameter == IN_FORCE_PARAMETER and row.keyed_on != DECISION_LABEL:
        f.blocking.append(
            f"{IN_FORCE_PARAMETER} must key on {DECISION_LABEL} (D-042): visibility is whether the provision "
            "exists at the hearing, never whether it reaches earlier facts"
        )
    if row.parameter == IN_FORCE_PARAMETER and kind != "boolean":
        f.blocking.append(f"{IN_FORCE_PARAMETER} needs a boolean value")
    populated = {
        "boolean": row.value_boolean is not None,
        "number": row.value_number is not None,
        "date_range": row.value_from is not None and row.value_to is not None,
        "text": bool(row.value_text),
    }
    if not populated[kind]:
        f.blocking.append(f"value_kind {kind} but its value field is empty")
    elif kind == "number" and row.value_number is not None:
        if row.value_number in numbers_mentioned(row.value_quote):
            f.checks.append(Check(name="value", status="MATCHED", detail=str(row.value_number)))
        else:
            f.checks.append(Check(name="value", status="NOT_CHECKABLE", detail=str(row.value_number)))
            f.judge.append(
                f"value {row.value_number:g} is not written in digits in its quote; check it against the words"
            )
    elif kind == "date_range":
        for name, value in (("value_from", row.value_from), ("value_to", row.value_to)):
            _date_in_quote(_parse_date(value, name, f), row.value_quote, name, f)

    for name, value, quote in (
        ("effective_from", row.effective_from, row.effective_from_quote),
        ("effective_to", row.effective_to, row.effective_to_quote),
    ):
        day = _parse_date(value, name, f)
        if day is not None:
            f.quote(f"{name}_quote", quote, source_text, required=True)
            _date_in_quote(day, quote, name, f)
    if row.effective_from is None and row.effective_to is None:
        f.judge.append(f"No commencement date is given in the text. Model's note: {row.commencement_note}")
    f.judge.append(
        "Is this the provision as it applied to cases on these dates (an ordinance later replaced by an Act, "
        "later amendments, retrospective effect)?"
    )
    f.judge.append(f"Is {row.keyed_on} the case date this rule turns on?")
    return f


def build_predicate(
    proposal: ProposedPredicate, record: LawRecord, predicate_id: str, source_text: str
) -> tuple[PredicateEntry | None, str | None, Findings]:
    f = Findings()
    f.quote("source_text", proposal.source_text, source_text, required=True)
    hashed: str | None = None
    try:
        hashed = item_hash(checklist_item(record, proposal.field, proposal.item_index))
    except (KeyError, IndexError) as exc:
        f.blocking.append(str(exc).strip("'\""))
    try:
        expression = json.loads(proposal.expression_json)
    except json.JSONDecodeError:
        f.blocking.append("expression_json is not valid JSON")
        return None, hashed, f
    entry: PredicateEntry | None = None
    if hashed is not None:
        try:
            entry = PredicateEntry.model_validate(
                {
                    "predicate_id": predicate_id,
                    "statute_id": record.statute_id,
                    "field": proposal.field,
                    "item_index": proposal.item_index,
                    "item_hash": hashed,
                    "kind": proposal.kind,
                    "inputs": [i.model_dump() for i in proposal.inputs],
                    "open_parameters": [p.model_dump() for p in proposal.open_parameters],
                    "expression": expression,
                    "error_code": proposal.error_code,
                    "source_text": proposal.source_text,
                    "status": "DRAFT",
                    "approved_by": None,
                    "version": 1,
                }
            )
        except ValidationError as exc:
            f.blocking += [f"{'.'.join(map(str, e['loc'])) or 'predicate'}: {e['msg']}" for e in exc.errors()]
    if entry is not None:
        written = numbers_mentioned(proposal.source_text)
        constants = [n.const for n in walk(entry.expression) if isinstance(n, ConstLeaf)]
        for const in constants:
            if isinstance(const, int | float) and not isinstance(const, bool) and const not in written:
                f.judge.append(f"constant {const:g} is not written in digits in the quoted text; check the words")
    f.judge.append(
        "Is this rule fixed literally by the text, rather than a reading a court had to settle (SPEC I3-12, D2)?"
    )
    return entry, hashed, f
