"""Two-model drafting (D-041). Extraction, not recall: each model sees only the Law DB record and excerpts of
one registered source document, located by search terms before any call is spent.

Agreement compares structured fields only (never wording). Identical proposals become one AGREED draft;
proposals for the same slot that differ become DISAGREED drafts pointing at each other; a proposal only one
model made is PRIMARY_ONLY or SECONDARY_ONLY. Nothing is resolved automatically.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Hashable
from datetime import UTC, datetime
from typing import TypeVar

from pydantic import BaseModel

from lexarena.drafting.checks import build_predicate, check_overlay_row
from lexarena.drafting.models import (
    Agreement,
    OverlayDraft,
    OverlayProposal,
    PredicateDraft,
    PredicateProposal,
    ProposedOverlayRow,
    ProposedPredicate,
)
from lexarena.drafting.sources import SourceRegistry, excerpts
from lexarena.llm.client import LLMClient
from lexarena.prompts import PromptStore, RenderedPrompt
from lexarena.schemas.codes import HARD_ERROR_CODES
from lexarena.schemas.config import AppConfig
from lexarena.schemas.law import LIST_FIELDS, SCALAR_FIELDS, LawRecord

ROLES = ("drafter_primary", "drafter_secondary")
P = TypeVar("P", bound=BaseModel)
DRAFT_ID_HASH_CHARS = 10  # literal-ok: draft ID suffix length
EXCERPT_SEPARATOR = "\n\n----- next excerpt -----\n\n"


class DraftingError(ValueError):
    pass


def _short_hash(*parts: object) -> str:
    digest = hashlib.sha256(json.dumps(parts, sort_keys=True, default=str).encode()).hexdigest()
    return digest[:DRAFT_ID_HASH_CHARS]


def _source_excerpts(cfg: AppConfig, registry: SourceRegistry, source_id: str, terms: list[str]) -> tuple[str, str]:
    text = registry.text(source_id)
    found = excerpts(text, terms, cfg.drafting.excerpt_chars, cfg.drafting.max_excerpts)
    if not found:
        raise DraftingError(f"search terms {terms} not found in {source_id}; no model call made")
    return text, EXCERPT_SEPARATOR.join(found)


def _pair(
    by_role: dict[str, list[P]], key: Callable[[P], Hashable], slot: Callable[[P], Hashable]
) -> list[tuple[P, Agreement, list[str]]]:
    """Each distinct proposal once, with its agreement label and the roles that made it."""
    primary, secondary = by_role[ROLES[0]], by_role[ROLES[1]]
    out: list[tuple[P, Agreement, list[str]]] = []
    unmatched_secondary = list(secondary)
    for item in primary:
        match = next((s for s in unmatched_secondary if key(s) == key(item)), None)
        if match is not None:
            unmatched_secondary.remove(match)
            out.append((item, "AGREED", list(ROLES)))
        else:
            out.append((item, "PRIMARY_ONLY", [ROLES[0]]))
    out += [(item, "SECONDARY_ONLY", [ROLES[1]]) for item in unmatched_secondary]
    # A slot both models filled differently is a disagreement, not two independent findings.
    for i, (item, label, roles) in enumerate(out):
        if label == "AGREED":
            continue
        rivals = [o for o in out if o[1] not in ("AGREED", label) and slot(o[0]) == slot(item)]
        if rivals:
            out[i] = (item, "DISAGREED", roles)
    return out


def _models(cfg: AppConfig) -> dict[str, str]:
    return {role: f"{role}:{cfg.models.by_role()[role].name}" for role in ROLES}


def _ask(llm: LLMClient, prompt: RenderedPrompt, schema: type[P], session_id: str) -> dict[str, P]:
    return {
        role: llm.complete_json(role=role, user=prompt, schema=schema, session_id=session_id).value for role in ROLES
    }


# ---------------------------------------------------------------- temporal_overlay


def _overlay_key(row: ProposedOverlayRow) -> Hashable:
    return (
        row.parameter,
        row.value_kind,
        row.value_boolean,
        row.value_number,
        row.value_from,
        row.value_to,
        row.value_text,
        row.keyed_on,
        row.effective_from,
        row.effective_to,
    )


def _overlay_quotes(row: ProposedOverlayRow) -> Hashable:
    return (row.source_text, row.value_quote, row.effective_from_quote, row.effective_to_quote)


def draft_overlay(
    llm: LLMClient,
    cfg: AppConfig,
    prompts: PromptStore,
    record: LawRecord,
    registry: SourceRegistry,
    source_id: str,
    terms: list[str],
) -> list[OverlayDraft]:
    source_text, excerpt_text = _source_excerpts(cfg, registry, source_id, terms)
    source = registry.get(source_id)
    prompt = prompts.render(
        cfg.prompts.draft_overlay.id,
        cfg.prompts.draft_overlay.version,
        statute=json.dumps(record.to_document(), indent=1, ensure_ascii=False),
        source_title=f"{source.title} ({source.reference}, {source.issued_on.isoformat()})",
        excerpts=excerpt_text,
        date_labels=", ".join(cfg.vocabulary.case_date_labels),
        parameters=", ".join(cfg.vocabulary.overlay_parameters),
    )
    answers = _ask(llm, prompt, OverlayProposal, f"draft-overlay-{record.statute_id}")
    paired = _pair(
        {role: list(a.rows) for role, a in answers.items()}, _overlay_key, lambda r: (r.parameter, r.keyed_on)
    )
    models = _models(cfg)
    drafts = []
    for row, agreement, roles in paired:
        found = check_overlay_row(row, source_text, cfg.vocabulary)
        drafts.append(
            OverlayDraft(
                kind="temporal_overlay",
                draft_id=f"OV_{record.statute_id}_{_short_hash(source_id, _overlay_key(row), _overlay_quotes(row))}",
                statute_id=record.statute_id,
                source_id=source_id,
                source_text_sha256=source.text_sha256,
                status="DRAFT",
                decided_by=None,
                decided_on=None,
                decision_note=None,
                agreement=agreement,
                conflicts_with=[],
                proposed_by=[models[r] for r in roles],
                row=row,
                checks=found.checks,
                blocking_problems=found.blocking,
                reviewer_must_judge=found.judge,
                created_at=datetime.now(UTC),
            )
        )
    _link_conflicts(drafts, lambda d: (d.row.parameter, d.row.keyed_on) if isinstance(d, OverlayDraft) else None)
    return drafts


# ---------------------------------------------------------------- predicate_registry


def _predicate_key(p: ProposedPredicate) -> Hashable:
    try:
        expression = json.dumps(json.loads(p.expression_json), sort_keys=True)
    except json.JSONDecodeError:
        expression = p.expression_json
    inputs = tuple(sorted((i.name, i.source) for i in p.inputs))
    params = tuple(sorted((o.name, tuple(o.options)) for o in p.open_parameters))
    return (p.field, p.item_index, p.kind, expression, inputs, params, p.error_code)


def _indexed_checklist(record: LawRecord) -> str:
    lines = []
    for field in LIST_FIELDS:
        for i, item in enumerate(getattr(record.diagnostic_checklist, field)):
            lines.append(f"{field}[{i}]: {item}")
    lines.append(f"financial_threshold: {json.dumps(record.diagnostic_checklist.financial_threshold.to_document())}")
    lines += [f"{f}: {getattr(record.procedural_timelines, f)}" for f in SCALAR_FIELDS[1:]]
    return "\n".join(lines)


def draft_predicate(
    llm: LLMClient,
    cfg: AppConfig,
    prompts: PromptStore,
    record: LawRecord,
    registry: SourceRegistry,
    source_id: str,
    terms: list[str],
) -> list[PredicateDraft]:
    source_text, excerpt_text = _source_excerpts(cfg, registry, source_id, terms)
    source = registry.get(source_id)
    prompt = prompts.render(
        cfg.prompts.draft_predicate.id,
        cfg.prompts.draft_predicate.version,
        statute_id=record.statute_id,
        section_title=record.section_title,
        checklist=_indexed_checklist(record),
        source_title=f"{source.title} ({source.reference}, {source.issued_on.isoformat()})",
        excerpts=excerpt_text,
        error_codes=", ".join(sorted(HARD_ERROR_CODES)),
        date_labels=", ".join(cfg.vocabulary.case_date_labels),
    )
    answers = _ask(llm, prompt, PredicateProposal, f"draft-predicate-{record.statute_id}")
    paired = _pair(
        {role: list(a.predicates) for role, a in answers.items()}, _predicate_key, lambda p: (p.field, p.item_index)
    )
    models = _models(cfg)
    drafts = []
    for proposal, agreement, roles in paired:
        draft_id = f"PR_{record.statute_id}_{_short_hash(source_id, _predicate_key(proposal), proposal.source_text)}"
        entry, hashed, found = build_predicate(proposal, record, draft_id, source_text)
        drafts.append(
            PredicateDraft(
                kind="predicate_registry",
                draft_id=draft_id,
                statute_id=record.statute_id,
                source_id=source_id,
                source_text_sha256=source.text_sha256,
                status="DRAFT",
                decided_by=None,
                decided_on=None,
                decision_note=None,
                agreement=agreement,
                conflicts_with=[],
                proposed_by=[models[r] for r in roles],
                proposal=proposal,
                item_hash=hashed,
                entry=entry,
                checks=found.checks,
                blocking_problems=found.blocking,
                reviewer_must_judge=found.judge,
                created_at=datetime.now(UTC),
            )
        )
    _link_conflicts(
        drafts,
        lambda d: (d.proposal.field, d.proposal.item_index) if isinstance(d, PredicateDraft) else None,
    )
    return drafts


def _link_conflicts(drafts: list[OverlayDraft] | list[PredicateDraft], slot: Callable[..., Hashable]) -> None:
    for draft in drafts:
        if draft.agreement == "DISAGREED":
            draft.conflicts_with = [
                d.draft_id for d in drafts if d is not draft and d.agreement == "DISAGREED" and slot(d) == slot(draft)
            ]
