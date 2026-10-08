"""What a judge reads (ARCHITECTURE §5; SPEC E1, E6; D-048), rendered field by field from an explicit allow-list.

- The case: the agent view only (no simulation date, build data or split; D-035). Parties appear by pseudonym, legal
  status and side. Agent names (`represented_by_agent`) and model names never appear: the sides are "Petitioner's
  counsel" and "Respondent's counsel" (SPEC E1).
- The law: the statutes the bench may cite, as they apply on the case dates (`StatuteView`, resolved by the caller).
  A threshold that changes over time is shown with its dated value when an approved overlay gives one, and the stored
  Law DB figure is marked as not verified for the case date otherwise (D-062).
- Precedents: only those counsel cited, fetched by ID through the judge's `get_precedent` tool, so the case's date
  cut-off and exclusion list apply (SPEC I3-6, D-052). Judges never search.
- Submissions: each side's published turns as one block, in the presentation order being tested, with turn numbers so
  replies stay traceable. Only FLAGGED hard errors are shown (SPEC E1), never THEMIS warnings, notes or scores.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass

from lexarena.schemas.base import SIDES, Side
from lexarena.schemas.bench import PresentationOrder
from lexarena.schemas.case import AgentCaseView, SimulationSide
from lexarena.schemas.retrieval import PrecedentExcerpt, PrecedentView
from lexarena.schemas.transcript import PublishedTurn
from lexarena.storage.temporal import StatuteView

COUNSEL: dict[Side, str] = {"PETITIONER": "Petitioner's counsel", "RESPONDENT": "Respondent's counsel"}
PARTY_SIDE_LABEL: dict[SimulationSide, str] = {
    "PETITIONER": COUNSEL["PETITIONER"],
    "RESPONDENT": COUNSEL["RESPONDENT"],
    "PROFORMA": "not represented (proforma party)",
}
SIDE_ORDER: dict[PresentationOrder, tuple[Side, Side]] = {
    "PETITIONER_FIRST": ("PETITIONER", "RESPONDENT"),
    "RESPONDENT_FIRST": ("RESPONDENT", "PETITIONER"),
}
PRECEDENT_PART = "ratio"
NONE = "(none)"

PrecedentFetcher = Callable[..., PrecedentExcerpt | PrecedentView | None]


@dataclass(frozen=True)
class PrecedentText:
    precedent_uid: str
    case_title: str
    decision_date: str
    text: str


def _unique(values: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(v for v in values if v))


def statutes_for_bench(case: AgentCaseView, turns: list[PublishedTurn]) -> list[str]:
    """Every statute ID the bench may need: invoked by the case, named by a framed issue, or relied on in a claim.
    The caller resolves each as of the case dates; IDs unknown or not in force simply drop out."""
    return _unique(
        [
            *case.metadata.statutes_invoked,
            *(s for issue in case.framed_issues for s in issue.statutes),
            *(c.statute_id or "" for t in turns for c in t.claims),
        ]
    )


def cited_precedent_uids(turns: list[PublishedTurn]) -> list[str]:
    return _unique(uid for t in turns for c in t.claims for uid in c.precedent_ids)


def fetch_precedents(uids: list[str], fetch: PrecedentFetcher) -> dict[str, PrecedentText]:
    """The cited precedents the judge may read: unknown, too late or excluded ones come back None and are left out."""
    found: dict[str, PrecedentText] = {}
    for uid in uids:
        got = fetch(uid, PRECEDENT_PART)
        if isinstance(got, PrecedentExcerpt):
            found[uid] = PrecedentText(uid, got.case_title, got.decision_date, got.text)
        elif isinstance(got, PrecedentView):
            found[uid] = PrecedentText(uid, got.case_title, got.decision_date, got.ratio_decidendi)
    return found


def record_ids(case: AgentCaseView) -> set[str]:
    r = case.record
    return {
        *(f.fact_id for f in r.stipulated_facts),
        *(c.fact_id for c in r.contested_facts),
        *(e.exhibit_id for e in r.exhibits),
        *(a.amount_id for a in r.amounts),
    }


# ---------------------------------------------------------------- case


def render_case(case: AgentCaseView) -> str:
    meta, r = case.metadata, case.record
    side_of = {p.party_id: p for p in case.parties}
    lines = [f"Forum: {meta.forum}. Proceeding: {meta.proceeding_type}.", "", "PARTIES"]
    for p in case.parties:
        position = f", {p.appeal_position}" if p.appeal_position else ""
        side = PARTY_SIDE_LABEL[p.simulation_side]
        lines.append(f"- {p.pseudonym}: {p.status}{position}; {side}")
    lines += ["", "BACKGROUND", case.factual_background, "", "RECORD"]
    lines += [f"[{f.fact_id}] (stipulated) {f.text}" for f in r.stipulated_facts]
    for c in r.contested_facts:
        lines += [
            f"[{c.fact_id}] (contested) {c.question}",
            f"    Petitioner's version: {c.petitioner_version}",
            f"    Respondent's version: {c.respondent_version}",
        ]
    for e in r.exhibits:
        filer = side_of[e.filed_by].pseudonym if e.filed_by in side_of else e.filed_by
        lines.append(f"[{e.exhibit_id}] (exhibit, filed by {filer}, authenticity {e.authenticity}) {e.title}")
        lines += [f"    known content: {k}" for k in e.known_contents]
        lines.append("    nothing else is known about this document")
    for a in r.amounts:
        when = f" on {a.date.isoformat()}" if a.date else ""
        lines.append(f"[{a.amount_id}] (amount) {a.label}: INR {a.value_inr}{when} (from {a.fact_id})")
    lines += ["", "KEY DATES"]
    lines += [f"- {d.label}: {d.date.isoformat()} (from {d.fact_id})" for d in meta.key_dates] or [NONE]
    lines += ["", "PROCEDURAL HISTORY"]
    lines += [
        f"{s.step}. {s.date.isoformat()} {s.forum}: {s.event} (from {s.fact_id})" for s in case.procedural_history
    ]
    lower = case.lower_forum_order
    lines += ["", "ORDER UNDER CHALLENGE"]
    if lower.exists:
        lines.append(f"{lower.forum}: {lower.result}. {lower.reasons_summary or ''}".strip())
        lines += [f"- direction: {d}" for d in lower.directions]
    else:
        lines.append(NONE)
    lines += ["", "RELIEFS SOUGHT"]
    for side in SIDES:
        lines += [f"- {COUNSEL[side]}: {relief}" for relief in getattr(case.reliefs_sought, side)]
    lines += ["", "PRESUMPTIONS", *(f"- {p}" for p in case.presumptions)]
    return "\n".join(lines)


def render_issues(case: AgentCaseView) -> str:
    return "\n".join(
        f"[{i.issue_id}] {i.question} (statutes: {', '.join(i.statutes) or NONE})" for i in case.framed_issues
    )


# ---------------------------------------------------------------- law


def _dated_values(view: StatuteView) -> list[str]:
    return [f"    {a.parameter} = {a.value!r} (applies on this case's dates)" for a in view.applied]


def render_statutes(views: dict[str, StatuteView]) -> str:
    if not views:
        return NONE
    blocks: list[str] = []
    for sid, view in views.items():
        rec = view.record
        lines = [f"[{sid}] {rec.act_name}, section {rec.section_number}: {rec.section_title} ({view.in_force})"]
        lines.append(f"    summary: {rec.statutory_summary}")
        checklist = rec.diagnostic_checklist
        for name in ("applicant_eligibility", "mandatory_prerequisites", "statutory_bars", "saving_exceptions"):
            items: list[str] = getattr(checklist, name)
            lines += [f"    {name} {n}: {text}" for n, text in enumerate(items)]
        dated = _dated_values(view)
        threshold = checklist.financial_threshold
        if threshold.minimum_amount is not None and not dated:
            lines.append(
                f"    stored minimum amount: {threshold.minimum_amount} {threshold.currency or ''}".rstrip()
                + " (as stored today; not verified for this case's dates)"
            )
        timelines = rec.procedural_timelines
        for key in ("adjudication_window_days", "rectification_window_days"):
            value = getattr(timelines, key)
            if value is not None:
                lines.append(f"    {key}: {value}")
        lines += dated
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def render_precedents(precedents: dict[str, PrecedentText]) -> str:
    if not precedents:
        return NONE
    return "\n\n".join(
        f"[{p.precedent_uid}] {p.case_title}, decided {p.decision_date}\n    ratio: {p.text}"
        for p in precedents.values()
    )


# ---------------------------------------------------------------- submissions


def _render_turn(turn: PublishedTurn) -> str:
    lines = [
        f"Turn {turn.turn} ({turn.turn_type}; issues {', '.join(turn.issues_addressed) or NONE})",
        turn.published_text,
    ]
    for flag in turn.visible_flags:
        where = ", ".join([*flag.claim_ids, *flag.record_ids]) or "the turn"
        lines.append(f"    VERIFIER FLAG {flag.code} on {where}")
    return "\n".join(lines)


def render_submissions(case: AgentCaseView, turns: list[PublishedTurn], order: PresentationOrder) -> str:
    """Each side's grounds and turns as one block; `order` decides which block comes first (SPEC E1)."""
    blocks: list[str] = []
    for side in SIDE_ORDER[order]:
        lines = [f"=== SUBMISSIONS OF {COUNSEL[side].upper()} ===", "Grounds pleaded:"]
        lines += [f"- [{g.issue_id}] {g.ground}" for g in case.opening_positions.for_side(side)] or [NONE]
        own = [t for t in turns if t.speaker == side]
        lines += ["", *(_render_turn(t) for t in own)] if own else ["", "No turns."]
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)
