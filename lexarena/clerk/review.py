"""The owner's review file for one clerked case (S-007, D-056): each record item beside the full text of the
paragraphs it cites, with a tick box, then the flags, problems, overlaps and probe answer.

It shows the agent view and its agent-visible sources only, pseudonymised. The sealed ground truth is not written
to disk: read it with `lexarena clerk show CASE`, which goes through the REVIEW role and closes at the first session.
"""

from __future__ import annotations

from lexarena.clerk.pipeline import ClerkOutcome


def _sources(ids: list[str], sources: dict[str, str]) -> list[str]:
    return [f"  > **{s}**: {sources.get(s, '(not an agent-visible source)')}" for s in ids]


def render_review(outcome: ClerkOutcome, source_file: str) -> str:
    out = [f"# Clerk review: {outcome.case_id}", "", f"Source: `{source_file}`", ""]
    out += ["## Blocking problems", ""] + ([f"- {p}" for p in outcome.problems] or ["- none"]) + [""]
    out += ["## Flags", ""] + ([f"- **{f.code}**: {f.detail} ({f.resolution})" for f in outcome.flags] or ["- none"])
    out.append("")
    case = outcome.case
    if case is None:
        out.append("No agent view was built; fix the blocking problems first.")
        return "\n".join(out) + "\n"
    v = case.agent_view
    b = case.build
    out += [
        "## Build",
        "",
        f"- evidence_dependency: {b.evidence_dependency}; issues_source: {b.issues_source}",
        f"- memorisation probe: {b.memorization_probe}"
        + (f" (model answered: {outcome.probe.model_dump()})" if outcome.probe else ""),
        f"- excluded precedents ({len(b.excluded_precedent_ids)}):",
        *[f"  - [ ] {o.precedent_id} | {o.case_title} | {o.reason}" for o in outcome.overlaps],
        "",
        "## Metadata and parties",
        "",
        f"- forum {v.metadata.forum}; proceeding {v.metadata.proceeding_type}; statutes {v.metadata.statutes_invoked}",
        *[f"- [ ] key date {k.label} {k.date} (from {k.fact_id})" for k in v.metadata.key_dates],
        *[f"- [ ] {p.party_id} {p.pseudonym}: {p.status}, {p.simulation_side}, {p.appeal_position}" for p in v.parties],
        "",
        "## Record",
        "",
    ]
    r = v.record
    for f in r.stipulated_facts:
        out += [f"- [ ] **{f.fact_id}** {f.text}", *_sources(f.source_paras, outcome.sources)]
    for c in r.contested_facts:
        out += [
            f"- [ ] **{c.fact_id}** {c.question}",
            f"  - PETITIONER: {c.petitioner_version}",
            f"  - RESPONDENT: {c.respondent_version}",
            *_sources(c.source_paras, outcome.sources),
        ]
    for e in r.exhibits:
        out += [f"- [ ] **{e.exhibit_id}** {e.title} (filed by {e.filed_by}, {e.authenticity})"]
        out += [f"  - contains: {k}" for k in e.known_contents] + _sources(e.source_paras, outcome.sources)
    for a in r.amounts:
        out.append(
            f"- [ ] **{a.amount_id}** {a.label}: INR {a.value_inr:,} ({a.date}, party {a.party_id}, {a.fact_id})"
        )
    out += ["", "## Background, history, order below", "", v.factual_background, ""]
    out += [f"- [ ] step {s.step} {s.date} {s.forum}: {s.event} ({s.fact_id})" for s in v.procedural_history]
    lo = v.lower_forum_order
    out += [
        "",
        f"- [ ] order below: {lo.forum}, {lo.result}; {lo.reasons_summary}",
        *[f"  - {d}" for d in lo.directions],
    ]
    out += ["", "## Issues, reliefs, opening grounds", ""]
    out += [f"- [ ] **{i.issue_id}** ({i.raised_by}) {i.question} {i.statutes}" for i in v.framed_issues]
    for side in ("PETITIONER", "RESPONDENT"):
        out += [f"- [ ] relief ({side}): {x}" for x in getattr(v.reliefs_sought, side)]
        for g in v.opening_positions.for_side(side):
            out += [f"- [ ] ground ({side}, {g.issue_id}): {g.ground}", *_sources(g.source_paras, outcome.sources)]
    out += ["", "## Presumptions", "", *[f"- {p}" for p in v.presumptions]]
    return "\n".join(out) + "\n"
