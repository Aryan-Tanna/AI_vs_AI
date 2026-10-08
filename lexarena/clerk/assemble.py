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

from pydantic import ValidationError

from lexarena.schemas.case import AGENT_FOR_SIDE, AgentView, ExtractionFlag
from lexarena.schemas.clerk import AgentViewDraft
from lexarena.schemas.statute_alias import StatuteAliasTable
from lexarena.statute_ids import resolve_statute_id

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
