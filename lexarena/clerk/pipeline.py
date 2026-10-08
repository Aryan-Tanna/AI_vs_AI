"""The clerk, end to end (BUILD_PLAN Step 6; ARCHITECTURE §3; SPEC A, H; D-056 to D-059).

judgment PDF -> clean and split (code) -> entities and pseudonyms -> route paragraphs -> record facts from the
reasoning -> agent view (pseudonymised, agent-visible text only) -> sealed ground truth (whole judgment) -> checks:
literal values, leakage, grounds balance, second-family entailment -> precedent overlap -> memorisation probe ->
Case + CaseGroundTruth + JudgmentText, and a review file.

Nothing is stored here: the caller stores the three documents only when `problems` is empty, and the case is used
only after the owner's review (`build.human_reviewed`). Every step's model answer is checked by code first.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from lexarena.clerk.assemble import build_agent_view, build_ground_truth, evidence_dependency
from lexarena.clerk.checks import grounds_balance, leakage_problems, literal_problems
from lexarena.clerk.entailment import check_entailment
from lexarena.clerk.names import Pseudonymizer, assign_pseudonyms
from lexarena.clerk.overlap import Overlap, appeal_numbers, find_overlaps, probe_identified
from lexarena.clerk.steps import (
    extract_agent_view,
    extract_ground_truth,
    list_entities,
    render_visible_text,
    route_paragraphs,
    select_record_facts,
)
from lexarena.clerk.text import clean_pages, split_paragraphs
from lexarena.llm.client import LLMClient
from lexarena.prompts import PromptStore
from lexarena.schemas.case import Case, ExtractionFlag
from lexarena.schemas.clerk import ProbeAnswer
from lexarena.schemas.config import AppConfig
from lexarena.schemas.ground_truth import CaseGroundTruth
from lexarena.schemas.judgment import AGENT_VISIBLE_PARTS, JudgmentText
from lexarena.schemas.statute_alias import StatuteAliasTable

REASONING_PARTS = ("ANALYSIS", "CONCLUSION")


@dataclass
class ClerkOutcome:
    case_id: str
    case: Case | None
    truth: CaseGroundTruth | None
    judgment: JudgmentText
    problems: list[str] = field(default_factory=list)
    flags: list[ExtractionFlag] = field(default_factory=list)
    overlaps: list[Overlap] = field(default_factory=list)
    probe: ProbeAnswer | None = None
    sources: dict[str, str] = field(default_factory=dict)  # pseudonymised agent-visible text, for the review file


def clerk_judgment(
    pages: list[str],
    *,
    source_file: str,
    source_bytes: bytes,
    case_id: str,
    forum: str,
    decided: date,
    split_name: str,
    llm: LLMClient,
    prompts: PromptStore,
    cfg: AppConfig,
    known_statutes: set[str],
    aliases: StatuteAliasTable,
    precedent_payloads: list[dict[str, Any]],
) -> ClerkOutcome:
    c = cfg.clerk
    sid = f"clerk-{case_id}"
    cleaned = clean_pages(pages, c.furniture_min_page_share)
    split = split_paragraphs(cleaned, c.body_start_headings, c.max_paragraph_number_jump, c.running_text_min_chars)
    flags = [*cleaned.flags, *split.flags]
    problems: list[str] = []

    entities = list_entities(llm, prompts, cfg, split.header, split.paragraphs, session_id=sid)
    pseudo = Pseudonymizer(assign_pseudonyms(entities, case_key=case_id, seed=cfg.seed), c.generic_name_words)
    labels = route_paragraphs(llm, prompts, cfg, split.paragraphs, session_id=sid)
    paragraphs = [p.model_copy(update={"part": labels[p.para_id]}) for p in split.paragraphs]
    judgment = JudgmentText.model_validate(
        {
            "_id": case_id,
            "source_file": source_file,
            "source_sha256": hashlib.sha256(source_bytes).hexdigest(),
            "header": split.header,
            "paragraphs": [p.model_dump() for p in paragraphs],
        }
    )
    if not any(p.part == "CONCLUSION" for p in paragraphs):
        flags.append(
            ExtractionFlag(
                code="NO_CONCLUSION_PARAGRAPH",
                detail="no paragraph was routed as CONCLUSION (SPEC A5)",
                resolution="the outcome is read from the reasoning paragraphs; review the sealed conclusion",
            )
        )

    visible = [p.model_copy(update={"text": pseudo.apply(p.text)}) for p in paragraphs if p.part in AGENT_VISIBLE_PARTS]
    reasoning = [p for p in paragraphs if p.part in REASONING_PARTS]
    kept, dropped = select_record_facts(llm, prompts, cfg, reasoning, session_id=sid)
    flags += dropped
    kept = [s.model_copy(update={"text": pseudo.apply(s.text)}) for s in kept]
    sources = {p.para_id: p.text for p in visible} | {s.sentence_id: s.text for s in kept}

    draft = extract_agent_view(
        llm,
        prompts,
        cfg,
        render_visible_text(visible, kept),
        parties=pseudo.assigned,
        forum=forum,
        statute_ids=sorted(known_statutes),
        session_id=sid,
    )
    built = build_agent_view(
        draft,
        forum=forum,
        decision_date=decided,
        presumptions=c.presumptions,
        visible_sources=set(sources),
        known_statutes=known_statutes,
        aliases=aliases,
        date_labels=cfg.vocabulary.case_date_labels,
        pseudonyms={a.pseudonym for a in pseudo.assigned},
        party_statuses=cfg.vocabulary.party_statuses,
    )
    problems += built.problems
    flags += built.flags
    view = built.view
    if view is None:
        return ClerkOutcome(case_id, None, None, judgment, problems, flags, sources=sources)

    gt_draft = extract_ground_truth(
        llm,
        prompts,
        cfg,
        split.header,
        paragraphs,
        issues=view.framed_issues,
        reliefs=view.reliefs_sought,
        statute_ids=sorted(known_statutes),
        session_id=sid,
    )
    sealed = build_ground_truth(
        gt_draft,
        case_id=case_id,
        anonymization_map={a.pseudonym: a.entity.name for a in pseudo.assigned},
        issue_ids={i.issue_id for i in view.framed_issues},
        reliefs={"PETITIONER": view.reliefs_sought.PETITIONER, "RESPONDENT": view.reliefs_sought.RESPONDENT},
        paragraph_ids={p.para_id for p in paragraphs},
        known_statutes=known_statutes,
        aliases=aliases,
        expected_decision_date=decided,
    )
    problems += sealed.problems
    flags += sealed.flags
    truth = sealed.truth
    if truth is None:
        return ClerkOutcome(case_id, None, None, judgment, problems, flags, sources=sources)

    problems += literal_problems(view, sources)
    pleaded = [
        a.name
        for subs in (truth.real_submissions.PETITIONER, truth.real_submissions.RESPONDENT)
        for s in subs
        for a in s.authorities_cited
    ] + [a.name for a in truth.precedent_analysis]
    problems += leakage_problems(
        view,
        case_number=truth.citation.case_number,
        bench=truth.citation.bench,
        decision_date=truth.citation.decision_date,
        entities=entities,
        authority_names=pleaded,
        reasoning=[pseudo.apply(p.text) for p in reasoning],
        visible=list(sources.values()),
        cfg_markers=c.court_voice_markers,
        evaluative_words=c.evaluative_words,
        generic_words=c.generic_name_words,
        ngram=c.leakage_ngram,
    )
    if (balance := grounds_balance(view, c.grounds_max_ratio)) is not None:
        flags.append(balance)
    entail_problems, entail_flags = check_entailment(llm, prompts, cfg, view, sources, session_id=sid)
    problems += entail_problems
    flags += entail_flags

    numbers = appeal_numbers(f"{truth.citation.case_number} {truth.citation.arising_from or ''}")
    overlaps = find_overlaps(precedent_payloads, entities, case_numbers=numbers, generic_words=c.generic_name_words)
    probe = _probe(llm, prompts, cfg, view, session_id=sid)
    probe_text = " ".join(x or "" for x in (probe.case_name, probe.appeal_number))
    identified = probe.recognised and probe_identified(probe_text, entities, numbers, c.generic_name_words)

    case = Case.model_validate(
        {
            "_id": case_id,
            "split": split_name,
            "build": {
                "source_forum": forum,
                "evidence_dependency": evidence_dependency([f.driver for f in truth.issue_findings]),
                "issues_source": "FRAMED_BY_COURT"
                if any(p.part == "ISSUES" for p in paragraphs)
                else "DERIVED_FROM_SUBMISSIONS",
                "memorization_probe": "IDENTIFIED" if identified else "NOT_IDENTIFIED",
                "excluded_precedent_ids": sorted({o.precedent_id for o in overlaps}),
                "extraction_flags": [f.model_dump() for f in flags],
                "human_reviewed": False,
                "clerk_version": c.version,
            },
            "agent_view": view.model_dump(),
        }
    )
    return ClerkOutcome(case_id, case, truth, judgment, problems, flags, overlaps, probe, sources)


def _probe(llm: LLMClient, prompts: PromptStore, cfg: AppConfig, view: Any, *, session_id: str) -> ProbeAnswer:
    ref = cfg.prompts.clerk_probe
    shown = {
        "facts": view.factual_background,
        "issues": [i.question for i in view.framed_issues],
        "order_below": view.lower_forum_order.reasons_summary,
    }
    prompt = prompts.render(ref.id, ref.version, case=json.dumps(shown, ensure_ascii=False, indent=1))
    return llm.complete_json(role="lawyer", user=prompt, schema=ProbeAnswer, session_id=session_id).value
