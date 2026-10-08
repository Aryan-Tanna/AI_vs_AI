"""Assemble the agent view from the extractor's draft (BUILD_PLAN Step 6, D-056).

Code sets what the model must not decide: the forum, the simulation date (server-side only), the presumptions
(config) and which agent argues each side (SPEC I2). It refuses what it cannot verify; nothing is patched by a
guess:
- a party pseudonym that was not assigned (the model must reuse, never coin, pseudonyms) blocks the case;
- a source ID the agents cannot see (an ANALYSIS paragraph, a sentence that was not kept) blocks the case;
- the DECISION date as a key date blocks it (it would show agents the decision date); so does any label outside
  the shared vocabulary;
- a statute that resolves to no Law DB ID is dropped and flagged, never invented;
- the whole view must validate (no dangling fact, party or issue reference); a failure blocks the case.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Literal

from pydantic import ValidationError

from lexarena.schemas.case import AGENT_FOR_SIDE, AgentView, ExtractionFlag
from lexarena.schemas.clerk import AgentViewDraft, GroundTruthDraft
from lexarena.schemas.ground_truth import CaseGroundTruth
from lexarena.schemas.statute_alias import StatuteAliasTable
from lexarena.statute_ids import resolve_statute_id

EvidenceDependency = Literal["LAW_ONLY", "MIXED", "EVIDENCE_DECIDED"]
DECISION_LABEL = "DECISION"  # the simulation_date's label (vocabulary.case_date_labels, D-039)


@dataclass
class AssembledView:
    view: AgentView | None
    problems: list[str] = field(default_factory=list)  # blocking: the case is not stored until they are fixed
    flags: list[ExtractionFlag] = field(default_factory=list)


def _sources(d: AgentViewDraft) -> list[tuple[str, str]]:
    r = d.record
    pairs = [(f.fact_id, s) for f in r.stipulated_facts for s in f.source_paras]
    pairs += [(c.fact_id, s) for c in r.contested_facts for s in c.source_paras]
    pairs += [(e.exhibit_id, s) for e in r.exhibits for s in e.source_paras]
    for side in ("PETITIONER", "RESPONDENT"):
        grounds = d.opening_positions.for_side(side)
        pairs += [(f"{side} ground {i}", s) for i, g in enumerate(grounds, 1) for s in g.source_paras]
    return pairs


def _resolve(ids: list[str], known: set[str], aliases: StatuteAliasTable) -> tuple[list[str], list[str]]:
    found: list[str] = []
    dropped: list[str] = []
    for cited in ids:
        match, _ = resolve_statute_id(cited, known, aliases)
        if match is None:
            dropped.append(cited)
        elif match not in found:
            found.append(match)
    return found, dropped


def build_agent_view(
    draft: AgentViewDraft,
    *,
    forum: str,
    decision_date: date,
    presumptions: list[str],
    visible_sources: set[str],
    known_statutes: set[str],
    aliases: StatuteAliasTable,
    date_labels: list[str],
    pseudonyms: set[str],
    party_statuses: list[str],
) -> AssembledView:
    problems = [
        f"{item} cites {src}, which the agents cannot see"
        for item, src in _sources(draft)
        if src not in visible_sources
    ]
    problems += [
        f"party {p.party_id} has pseudonym {p.pseudonym!r}, which was not assigned to anyone"
        for p in draft.parties
        if p.pseudonym not in pseudonyms
    ]
    allowed = set(date_labels) - {DECISION_LABEL}
    for kd in draft.key_dates:
        if kd.label == DECISION_LABEL:
            problems.append("key date DECISION would show agents the decision date")
        elif kd.label not in allowed:
            problems.append(f"key date label {kd.label} is not in vocabulary.case_date_labels")

    statutes, dropped = _resolve(draft.statutes_invoked, known_statutes, aliases)
    issues = []
    for issue in draft.framed_issues:
        ids, lost = _resolve(issue.statutes, known_statutes, aliases)
        dropped += lost
        issues.append(issue.model_copy(update={"statutes": ids}))
    flags = []
    by_position: dict[str, set[str]] = {}
    for p in draft.parties:
        if p.appeal_position:
            by_position.setdefault(p.appeal_position, set()).add(p.status)
    mixed = {pos: sorted(st) for pos, st in by_position.items() if len(st) > 1}
    if mixed:
        flags.append(
            ExtractionFlag(
                code="PARTY_POSITION_STATUS_MISMATCH",
                detail=f"parties sharing a cause-title position hold different statuses: {mixed}",
                resolution="kept as extracted; review each party's status against the cause title",
            )
        )
    unlisted = sorted({p.status for p in draft.parties} - set(party_statuses))
    if unlisted:
        flags.append(
            ExtractionFlag(
                code="PARTY_STATUS_UNLISTED",
                detail=f"party statuses outside vocabulary.party_statuses: {unlisted}",
                resolution="kept as extracted; review, then extend the vocabulary or correct the status",
            )
        )
    if dropped:
        flags.append(
            ExtractionFlag(
                code="STATUTE_NOT_IN_LAW_DB",
                detail=f"statute references with no Law DB ID: {sorted(set(dropped))}",
                resolution="left out of statutes_invoked and the issues' statutes",
            )
        )

    raw = {
        "metadata": {
            "forum": forum,
            "proceeding_type": draft.proceeding_type,
            "statutes_invoked": statutes,
            "simulation_date": decision_date,
            "key_dates": [kd.model_dump() for kd in draft.key_dates],
        },
        "parties": [
            {**p.model_dump(), "represented_by_agent": AGENT_FOR_SIDE[p.simulation_side]} for p in draft.parties
        ],
        "factual_background": draft.factual_background,
        "record": draft.record.model_dump(),
        "procedural_history": [s.model_dump() for s in draft.procedural_history],
        "lower_forum_order": draft.lower_forum_order.model_dump(),
        "framed_issues": [i.model_dump() for i in issues],
        "reliefs_sought": draft.reliefs_sought.model_dump(),
        "opening_positions": draft.opening_positions.model_dump(),
        "presumptions": list(presumptions),
    }
    try:
        view = AgentView.model_validate(raw)
    except ValidationError as exc:
        problems += [f"{'.'.join(map(str, e['loc'])) or '<view>'}: {e['msg']}" for e in exc.errors()]
        return AssembledView(view=None, problems=problems, flags=flags)
    return AssembledView(view=view, problems=problems, flags=flags)


# ---------------------------------------------------------------- sealed ground truth (SPEC H2)


@dataclass
class AssembledTruth:
    truth: CaseGroundTruth | None
    problems: list[str] = field(default_factory=list)
    flags: list[ExtractionFlag] = field(default_factory=list)


def _clean_id(source: str) -> str:
    """'[P3]' or ' P3 ' -> 'P3': formatting only; the ID must still exist to pass."""
    return source.strip().strip("[]").strip()


def _normalise_sources(draft: GroundTruthDraft) -> GroundTruthDraft:
    data = draft.model_dump(mode="json")
    for side in ("PETITIONER", "RESPONDENT"):
        for sub in data["real_submissions"][side]:
            sub["source_paras"] = [_clean_id(s) for s in sub["source_paras"]]
    for key in ("statutory_analysis", "precedent_analysis", "issue_findings"):
        for item in data[key]:
            item["source_paras"] = [_clean_id(s) for s in item["source_paras"]]
    return GroundTruthDraft.model_validate(data)


def evidence_dependency(drivers: list[str]) -> EvidenceDependency:
    """SPEC A7: every issue decided on law -> LAW_ONLY; every issue on evidence -> EVIDENCE_DECIDED; else MIXED."""
    kinds = set(drivers)
    if kinds == {"LAW"}:
        return "LAW_ONLY"
    if kinds == {"EVIDENCE"}:
        return "EVIDENCE_DECIDED"
    return "MIXED"


def build_ground_truth(
    draft: GroundTruthDraft,
    *,
    case_id: str,
    anonymization_map: dict[str, str],
    issue_ids: set[str],
    reliefs: dict[str, list[str]],
    paragraph_ids: set[str],
    known_statutes: set[str],
    aliases: StatuteAliasTable,
    expected_decision_date: date,
) -> AssembledTruth:
    """Seal the ground truth only if it lines up with the agent view: the same issues (each with a finding), only
    reliefs the agents were shown, only real paragraphs, and the decision date of the dev manifest."""
    draft = _normalise_sources(draft)
    problems: list[str] = []
    found = [f.issue_id for f in draft.issue_findings]
    problems += [f"finding for issue {i}, which the agent view does not frame" for i in found if i not in issue_ids]
    problems += [f"issue {i} has no finding" for i in sorted(issue_ids) if i not in found]
    shown = {r for side in reliefs.values() for r in side}
    problems += [
        f"relief {r.relief!r} was never shown to the agents" for r in draft.conclusion.reliefs if r.relief not in shown
    ]
    if draft.citation.decision_date != expected_decision_date:
        problems.append(
            f"decision date {draft.citation.decision_date} differs from the dev manifest's {expected_decision_date}"
        )
    cited: list[tuple[str, str]] = []
    for side in ("PETITIONER", "RESPONDENT"):
        subs = draft.real_submissions.PETITIONER if side == "PETITIONER" else draft.real_submissions.RESPONDENT
        cited += [(f"{side} submission {i}", s) for i, sub in enumerate(subs, 1) for s in sub.source_paras]
    cited += [(f"statutory analysis {a.statute_id}", s) for a in draft.statutory_analysis for s in a.source_paras]
    cited += [(f"precedent {a.name}", s) for a in draft.precedent_analysis for s in a.source_paras]
    cited += [(f"finding {f.issue_id}", s) for f in draft.issue_findings for s in f.source_paras]
    problems += [
        f"{item} cites {src}, which is not a paragraph of this judgment"
        for item, src in cited
        if src.split(".")[0] not in paragraph_ids
    ]

    dropped: list[str] = []
    data = draft.model_dump(mode="json")
    for side in ("PETITIONER", "RESPONDENT"):
        for sub in data["real_submissions"][side]:
            sub["statutes_cited"], lost = _resolve(sub["statutes_cited"], known_statutes, aliases)
            dropped += lost
    kept_analysis = []
    for a in data["statutory_analysis"]:
        ids, lost = _resolve([a["statute_id"], *a["interacts_with"]], known_statutes, aliases)
        dropped += lost
        if a["statute_id"] in lost:
            continue  # its subject has no Law DB record: reported, not stored under an invented ID
        a["statute_id"], a["interacts_with"] = ids[0], ids[1:]
        kept_analysis.append(a)
    data["statutory_analysis"] = kept_analysis
    flags = []
    if dropped:
        flags.append(
            ExtractionFlag(
                code="STATUTE_NOT_IN_LAW_DB",
                detail=f"ground-truth statute references with no Law DB ID: {sorted(set(dropped))}",
                resolution="left out of the sealed record's statute lists",
            )
        )
    try:
        truth = CaseGroundTruth.model_validate(
            {**data, "_id": case_id, "access": "SEALED_UNTIL_VERDICT", "anonymization_map": anonymization_map}
        )
    except ValidationError as exc:
        problems += [f"{'.'.join(map(str, e['loc'])) or '<truth>'}: {e['msg']}" for e in exc.errors()]
        return AssembledTruth(truth=None, problems=problems, flags=flags)
    return AssembledTruth(truth=truth, problems=problems, flags=flags)
