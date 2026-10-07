"""Load APPROVED review items into the side collections (non-negotiable 8; BUILD_PLAN Step 3).

The review file is not trusted on its own: at load time every APPROVED item is re-verified against the
registered source (file hashes, the text hash the draft was made from, every quote and date) and, for
predicates, against the current Law DB record. Anything that fails is skipped with its reason; DRAFT and
REJECTED items are never touched.
"""

from __future__ import annotations

from pydantic import BaseModel

from lexarena.drafting.checks import build_predicate, check_overlay_row
from lexarena.drafting.models import OverlayDraft, PredicateDraft, ProposedOverlayRow
from lexarena.drafting.review import ReviewStore
from lexarena.drafting.sources import LegalSource, SourceError, SourceIntegrityError, SourceRegistry
from lexarena.schemas.config import VocabularyConfig
from lexarena.schemas.law import LawRecord
from lexarena.schemas.overlay import DateRange, TemporalOverlayRow
from lexarena.storage.law import LawRepository, OverlayRejectedError, PredicateRejectedError


class ReviewLoadReport(BaseModel):
    loaded: list[str]
    skipped: dict[str, str]
    not_approved: int


class _SkipError(Exception):
    pass


def _value(row: ProposedOverlayRow) -> bool | int | float | DateRange | str:
    if row.value_kind == "boolean" and row.value_boolean is not None:
        return row.value_boolean
    if row.value_kind == "number" and row.value_number is not None:
        return int(row.value_number) if row.value_number.is_integer() else row.value_number
    if row.value_kind == "date_range" and row.value_from and row.value_to:
        return DateRange.model_validate({"from": row.value_from, "to": row.value_to})
    if row.value_kind == "text" and row.value_text:
        return row.value_text
    raise _SkipError(f"value_kind {row.value_kind} has no value")


def _source(registry: SourceRegistry, draft: OverlayDraft | PredicateDraft) -> tuple[LegalSource, str]:
    try:
        source, text = registry.get(draft.source_id), registry.text(draft.source_id)
    except (SourceError, SourceIntegrityError) as exc:
        raise _SkipError(str(exc)) from exc
    if source.text_sha256 != draft.source_text_sha256:
        raise _SkipError(f"{draft.source_id} text differs from the version this item was drafted from")
    return source, text


def _load_overlay(draft: OverlayDraft, registry: SourceRegistry, law: LawRepository, vocab: VocabularyConfig) -> None:
    source, text = _source(registry, draft)
    found = check_overlay_row(draft.row, text, vocab, source.issued_on)
    if found.blocking:
        raise _SkipError("; ".join(found.blocking))
    row = draft.row
    overlay = TemporalOverlayRow.model_validate(
        {
            "overlay_id": draft.draft_id,
            "statute_id": draft.statute_id,
            "parameter": row.parameter,
            "value": _value(row),
            "keyed_on": row.keyed_on,
            "effective_from": row.effective_from,
            "effective_to": row.effective_to,
            "source_ref": f"{source.reference}; {source.title} [{source.source_id}]",
            "source_text": row.source_text,
            "status": "APPROVED",
            "approved_by": draft.decided_by,
            "version": 1,
        }
    )
    try:
        law.put_overlay(overlay)
    except OverlayRejectedError as exc:
        raise _SkipError(str(exc)) from exc


def _load_predicate(draft: PredicateDraft, registry: SourceRegistry, law: LawRepository) -> None:
    _, text = _source(registry, draft)
    record = law.get_record(draft.statute_id)
    if record is None:
        raise _SkipError(f"statute {draft.statute_id} is not in the Law DB")
    entry, hashed, found = build_predicate(draft.proposal, record, draft.draft_id, text)
    if hashed != draft.item_hash:
        raise _SkipError("the Law DB item has changed since this predicate was drafted; re-draft it")
    if found.blocking or entry is None:
        raise _SkipError("; ".join(found.blocking) or "the proposal is not a valid predicate")
    try:
        law.put_predicate(entry.model_copy(update={"status": "APPROVED", "approved_by": draft.decided_by}))
    except PredicateRejectedError as exc:
        raise _SkipError(str(exc)) from exc


def recheck(
    draft: OverlayDraft | PredicateDraft,
    registry: SourceRegistry,
    vocab: VocabularyConfig,
    record: LawRecord | None,
) -> OverlayDraft | PredicateDraft:
    """The draft with its checks recomputed now (approval and loading never rely on stored results)."""
    try:
        source, text = _source(registry, draft)
    except _SkipError as exc:
        return draft.model_copy(update={"blocking_problems": [str(exc)]})
    if isinstance(draft, OverlayDraft):
        found = check_overlay_row(draft.row, text, vocab, source.issued_on)
        return draft.model_copy(
            update={"checks": found.checks, "blocking_problems": found.blocking, "reviewer_must_judge": found.judge}
        )
    if record is None:
        return draft.model_copy(update={"blocking_problems": [f"statute {draft.statute_id} is not in the Law DB"]})
    _entry, hashed, found = build_predicate(draft.proposal, record, draft.draft_id, text)
    blocking = found.blocking + ([] if hashed == draft.item_hash else ["the Law DB item has changed since drafting"])
    return draft.model_copy(
        update={"checks": found.checks, "blocking_problems": blocking, "reviewer_must_judge": found.judge}
    )


def load_approved(
    store: ReviewStore, registry: SourceRegistry, law: LawRepository, vocab: VocabularyConfig
) -> ReviewLoadReport:
    loaded: list[str] = []
    skipped: dict[str, str] = {}
    not_approved = 0
    for draft in store.all():
        if draft.status != "APPROVED":
            not_approved += 1
            continue
        try:
            if not draft.decided_by:
                raise _SkipError("approved without a reviewer name")
            if isinstance(draft, OverlayDraft):
                _load_overlay(draft, registry, law, vocab)
            else:
                _load_predicate(draft, registry, law)
            loaded.append(draft.draft_id)
        except _SkipError as exc:
            skipped[draft.draft_id] = str(exc)
    return ReviewLoadReport(loaded=loaded, skipped=skipped, not_approved=not_approved)
