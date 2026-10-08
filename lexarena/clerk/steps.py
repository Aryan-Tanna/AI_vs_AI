"""Clerk steps that ask a model (BUILD_PLAN Step 6, D-056). Each answer is checked by code before use; an
incomplete answer stops the case instead of being patched by a guess.

- `list_entities`: every named person and organisation, with the name forms the judgment uses (reads the whole
  judgment, since a short form can appear anywhere).
- `route_paragraphs`: one part label per paragraph (SPEC H0). The router sees each paragraph's opening only
  (`clerk.route_chars_per_paragraph`), which is enough to tell a submission from a finding and keeps the call small.
"""

from __future__ import annotations

import re
from collections import Counter

from lexarena.clerk.assemble import DECISION_LABEL
from lexarena.clerk.scan import court_voice_hits
from lexarena.llm.client import LLMClient
from lexarena.prompts import PromptStore
from lexarena.schemas.case import ExtractionFlag, FramedIssue, ReliefsSought
from lexarena.schemas.clerk import (
    AgentViewDraft,
    AssignedPseudonym,
    CourtSentence,
    EntityList,
    GroundTruthDraft,
    NamedEntity,
    RecordFactIds,
    RouteResult,
)
from lexarena.schemas.config import AppConfig
from lexarena.schemas.judgment import JudgmentParagraph, JudgmentPart

ROLE = "clerk_primary"
CUT_MARK = "…"


class RouteError(ValueError):
    """The router did not give exactly one label per paragraph."""


def render_paragraphs(paragraphs: list[JudgmentParagraph], chars: int | None = None) -> str:
    def body(p: JudgmentParagraph) -> str:
        return p.text if chars is None or len(p.text) <= chars else p.text[:chars] + CUT_MARK

    return "\n\n".join(f"[{p.para_id}] {body(p)}" for p in paragraphs)


def list_entities(
    llm: LLMClient,
    prompts: PromptStore,
    cfg: AppConfig,
    header: str,
    paragraphs: list[JudgmentParagraph],
    *,
    session_id: str,
) -> list[NamedEntity]:
    ref = cfg.prompts.clerk_entities
    prompt = prompts.render(ref.id, ref.version, header=header, body=render_paragraphs(paragraphs))
    return llm.complete_json(role=ROLE, user=prompt, schema=EntityList, session_id=session_id).value.entities


def route_paragraphs(
    llm: LLMClient, prompts: PromptStore, cfg: AppConfig, paragraphs: list[JudgmentParagraph], *, session_id: str
) -> dict[str, JudgmentPart]:
    ref = cfg.prompts.clerk_route
    prompt = prompts.render(
        ref.id, ref.version, paragraphs=render_paragraphs(paragraphs, cfg.clerk.route_chars_per_paragraph)
    )
    labels = llm.complete_json(role=ROLE, user=prompt, schema=RouteResult, session_id=session_id).value.labels
    expected = [p.para_id for p in paragraphs]
    counts = Counter(label.para_id for label in labels)
    missing = [pid for pid in expected if counts[pid] == 0]
    repeated = sorted(pid for pid, n in counts.items() if n > 1)
    unknown = sorted(set(counts) - set(expected))
    if missing or repeated or unknown:
        raise RouteError(f"routing incomplete: missing {missing}, repeated {repeated}, unknown {unknown}")
    return {label.para_id: label.part for label in labels}


# ---------------------------------------------------------------- record facts stated inside the reasoning (D-058)

# Abbreviations whose full stop never ends a sentence in Indian tribunal judgments (language, not data).
ABBREVIATIONS = (
    "No",
    "Nos",
    "Pvt",
    "Ltd",
    "Co",
    "Corp",
    "Vs",
    "vs",
    "v",
    "Rs",
    "Sr",
    "Jr",
    "Mr",
    "Mrs",
    "Ms",
    "Dr",
    "Sec",
    "Secs",
    "Art",
    "Arts",
    "Para",
    "Paras",
    "pp",
    "p",
    "Ld",
    "Smt",
    "Shri",
    "Sri",
    "M/s",
    "viz",
    "etc",
    "Hon",
    "Govt",
    "Dept",
    "Regn",
    "Reg",
    "Ref",
    "Annex",
    "Ex",
    "Exh",
    "Cl",
    "Sub",
    "St",
    "Rly",
    "Bros",
    "Ors",
    "Anr",
)
_ABBREV = re.compile(r"\b(" + "|".join(re.escape(a) for a in ABBREVIATIONS) + r")\.", re.IGNORECASE)
_DOTTED = re.compile(r"\b(?:[A-Za-z]\.){2,}")  # i.e. / e.g. / U.P.
_NUMBER_DOT = re.compile(r"(?<=\d)\.(?=\d)")  # 01.01.2001, 2.5
_INITIAL = re.compile(r"\b([A-Z])\.(?=\s+[A-Z])")  # "A. Kumar"
_HOLD = "\u0000"  # stands in for a protected full stop while splitting


def split_sentences(text: str) -> list[str]:
    protected = _DOTTED.sub(lambda m: m.group(0).replace(".", _HOLD), text)
    for pattern in (_ABBREV, _NUMBER_DOT, _INITIAL):
        protected = pattern.sub(lambda m: m.group(0).replace(".", _HOLD), protected)
    parts = re.split(r"(?<=[.?!])\s+(?=[\"'(\[A-Z0-9])", protected)
    return [p.replace(_HOLD, ".").strip() for p in parts if p.strip()]


def select_record_facts(
    llm: LLMClient, prompts: PromptStore, cfg: AppConfig, paragraphs: list[JudgmentParagraph], *, session_id: str
) -> tuple[list[CourtSentence], list[ExtractionFlag]]:
    """Record-fact sentences from reasoning paragraphs. The model picks them; code then drops any picked sentence
    in the court's voice or with an evaluative word, and flags it (SPEC A3, H5 rule 12)."""
    sentences = [
        CourtSentence(para_id=p.para_id, sentence_id=f"{p.para_id}.S{i}", text=s)
        for p in paragraphs
        for i, s in enumerate(split_sentences(p.text), 1)
    ]
    if not sentences:
        return [], []
    ref = cfg.prompts.clerk_record_facts
    rendered = "\n".join(f"[{s.sentence_id}] {s.text}" for s in sentences)
    prompt = prompts.render(ref.id, ref.version, sentences=rendered)
    picked = llm.complete_json(role=ROLE, user=prompt, schema=RecordFactIds, session_id=session_id).value
    by_id = {s.sentence_id: s for s in sentences}
    unknown = [i for i in picked.record_fact_ids if i not in by_id]
    if unknown:
        raise RouteError(f"record-fact selection named unknown sentences: {unknown}")
    kept: list[CourtSentence] = []
    flags: list[ExtractionFlag] = []
    for sid in dict.fromkeys(picked.record_fact_ids):
        s = by_id[sid]
        voice = court_voice_hits(s.text, cfg.clerk.court_voice_markers)
        words = [w for w in cfg.clerk.evaluative_words if re.search(rf"\b{re.escape(w)}\b", s.text, re.IGNORECASE)]
        if voice or words:
            flags.append(
                ExtractionFlag(
                    code="REASONING_DROPPED",
                    detail=f"{sid} was picked as a record fact but reads as reasoning ({voice + words})",
                    resolution="left out of the agent view",
                )
            )
        else:
            kept.append(s)
    return kept, flags


# ---------------------------------------------------------------- agent view (D-056)


def render_visible_text(paragraphs: list[JudgmentParagraph], sentences: list[CourtSentence]) -> str:
    """The extractor's whole input: agent-visible paragraphs, then the record-fact sentences kept from the
    reasoning, each with its ID. Both are already pseudonymised by the caller."""
    blocks = [f"[{p.para_id}] {p.text}" for p in paragraphs] + [f"[{s.sentence_id}] {s.text}" for s in sentences]
    return "\n\n".join(blocks)


def render_roster(parties: list[AssignedPseudonym]) -> str:
    """Pseudonyms of the cause-title parties with their kind and position; never the real names."""
    rows = [
        f"- {a.pseudonym}: cause-title position {a.entity.cause_title_role}; kind {a.entity.kind}"
        for a in parties
        if a.entity.cause_title_role
    ]
    return "\n".join(rows) if rows else "- (no party named in the cause title)"


def extract_agent_view(
    llm: LLMClient,
    prompts: PromptStore,
    cfg: AppConfig,
    text: str,
    *,
    parties: list[AssignedPseudonym],
    forum: str,
    statute_ids: list[str],
    session_id: str,
) -> AgentViewDraft:
    ref = cfg.prompts.clerk_agent_view
    labels = [label for label in cfg.vocabulary.case_date_labels if label != DECISION_LABEL]
    prompt = prompts.render(
        ref.id,
        ref.version,
        parties=render_roster(parties),
        party_statuses=", ".join(cfg.vocabulary.party_statuses),
        forum=forum,
        date_labels=", ".join(labels),
        evaluative_words=", ".join(cfg.clerk.evaluative_words),
        statute_ids=", ".join(sorted(statute_ids)),
        text=text,
    )
    return llm.complete_json(role=ROLE, user=prompt, schema=AgentViewDraft, session_id=session_id).value


# ---------------------------------------------------------------- sealed ground truth (SPEC H2)


def extract_ground_truth(
    llm: LLMClient,
    prompts: PromptStore,
    cfg: AppConfig,
    header: str,
    paragraphs: list[JudgmentParagraph],
    *,
    issues: list[FramedIssue],
    reliefs: ReliefsSought,
    statute_ids: list[str],
    session_id: str,
) -> GroundTruthDraft:
    """Reads the whole judgment with real names: it runs in the sealed process and its output is sealed."""
    ref = cfg.prompts.clerk_ground_truth
    prompt = prompts.render(
        ref.id,
        ref.version,
        issues="\n".join(f"- {i.issue_id}: {i.question}" for i in issues),
        reliefs="\n".join(f"- {side}: {r}" for side in ("PETITIONER", "RESPONDENT") for r in getattr(reliefs, side)),
        statute_ids=", ".join(sorted(statute_ids)),
        header=header,
        body=render_paragraphs(paragraphs),
    )
    return llm.complete_json(role=ROLE, user=prompt, schema=GroundTruthDraft, session_id=session_id).value


def repair_agent_view(
    llm: LLMClient,
    prompts: PromptStore,
    cfg: AppConfig,
    text: str,
    previous: AgentViewDraft,
    problems: list[str],
    *,
    parties: list[AssignedPseudonym],
    session_id: str,
) -> AgentViewDraft:
    """One repair round (D-060): the extractor sees its own case file and the checker's problems, and must fix only
    those. Its answer goes through every check again."""
    ref = cfg.prompts.clerk_agent_view_repair
    prompt = prompts.render(
        ref.id,
        ref.version,
        problems="\n".join(f"- {p}" for p in problems),
        parties=render_roster(parties),
        text=text,
        previous=previous.model_dump_json(indent=1),
    )
    return llm.complete_json(role=ROLE, user=prompt, schema=AgentViewDraft, session_id=session_id).value
