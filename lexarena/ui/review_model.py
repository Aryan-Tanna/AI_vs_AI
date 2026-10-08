"""What the clerk-review viewer shows (D-056, S-007, R-003): pure, so it is testable without a browser.

Every reviewable item of a clerked case, with the judgment text it rests on: record items (F, C, EX, AM), key dates,
parties, opening grounds, and the sealed findings and conclusion. A source ID is a paragraph (`P4`) or a sentence of a
paragraph (`P4.S1`, numbered by the clerk's own sentence splitter, so the ID resolves to the same sentence).

The viewer is for the owner, in the REVIEW role, before a case's first session. It shows the real judgment text and the
real names in it; nothing here is ever given to an agent, THEMIS or a judge.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from lexarena.clerk.steps import split_sentences
from lexarena.schemas.case import Case
from lexarena.schemas.ground_truth import CaseGroundTruth
from lexarena.schemas.judgment import JudgmentText

SENTENCE_MARK = ".S"


@dataclass(frozen=True)
class Source:
    source_id: str
    para_id: str
    part: str | None
    page: int | None
    text: str  # the sentence for a sentence ID, the whole paragraph otherwise; "(not found)" when unknown
    found: bool


@dataclass(frozen=True)
class ReviewItem:
    item_id: str  # stable, unique within the case: what a tick is stored against
    section: str
    title: str
    lines: list[str]
    sources: list[Source]


@dataclass
class ReviewPage:
    case_id: str
    source_file: str
    flags: list[str]
    human_reviewed: bool
    items: list[ReviewItem] = field(default_factory=list)

    def sections(self) -> list[str]:
        return list(dict.fromkeys(i.section for i in self.items))


def resolve(source_id: str, judgment: JudgmentText) -> Source:
    para_id, _, sentence = source_id.partition(SENTENCE_MARK)
    para = next((p for p in judgment.paragraphs if p.para_id == para_id), None)
    if para is None:
        return Source(source_id, para_id, None, None, "(not found)", False)
    text = para.text
    if sentence:
        sentences = split_sentences(para.text)
        index = int(sentence) - 1 if sentence.isdigit() else -1
        if not 0 <= index < len(sentences):
            return Source(source_id, para_id, para.part, para.page, "(not found)", False)
        text = sentences[index]
    return Source(source_id, para_id, para.part, para.page, text, True)


def build_page(case: Case, truth: CaseGroundTruth, judgment: JudgmentText) -> ReviewPage:
    av, build = case.agent_view, case.build
    page = ReviewPage(
        case_id=case.id,
        source_file=judgment.source_file,
        flags=[f"{f.code}: {f.detail} ({f.resolution})" for f in build.extraction_flags],
        human_reviewed=build.human_reviewed,
    )

    def add(item_id: str, section: str, title: str, lines: list[str], source_ids: list[str]) -> None:
        page.items.append(ReviewItem(item_id, section, title, lines, [resolve(s, judgment) for s in source_ids]))

    fact_sources = {f.fact_id: f.source_paras for f in av.record.stipulated_facts}
    fact_sources |= {c.fact_id: c.source_paras for c in av.record.contested_facts}
    for p in av.parties:
        add(
            f"party:{p.party_id}",
            "Parties",
            f"{p.party_id} {p.pseudonym}",
            [f"{p.status}; {p.simulation_side}; {p.appeal_position or '-'}"],
            [],
        )
    for d in av.metadata.key_dates:
        add(
            f"date:{d.label}",
            "Key dates",
            f"{d.label} {d.date.isoformat()}",
            [f"from {d.fact_id}"],
            fact_sources.get(d.fact_id, []),
        )
    for f in av.record.stipulated_facts:
        add(f.fact_id, "Record", f"{f.fact_id} (stipulated)", [f.text], f.source_paras)
    for c in av.record.contested_facts:
        add(
            c.fact_id,
            "Record",
            f"{c.fact_id} (contested)",
            [c.question, f"Petitioner: {c.petitioner_version}", f"Respondent: {c.respondent_version}"],
            c.source_paras,
        )
    for e in av.record.exhibits:
        add(
            e.exhibit_id,
            "Record",
            f"{e.exhibit_id} (exhibit, {e.authenticity})",
            [e.title, *(f"contains: {k}" for k in e.known_contents)],
            e.source_paras,
        )
    for a in av.record.amounts:
        when = a.date.isoformat() if a.date else "-"
        add(
            a.amount_id,
            "Record",
            f"{a.amount_id} (amount)",
            [f"{a.label}: INR {a.value_inr} on {when}"],
            fact_sources.get(a.fact_id, []),
        )
    for i in av.framed_issues:
        add(f"issue:{i.issue_id}", "Issues", i.issue_id, [i.question, f"statutes: {', '.join(i.statutes) or '-'}"], [])
    for side in ("PETITIONER", "RESPONDENT"):
        for n, g in enumerate(av.opening_positions.for_side(side), 1):
            add(
                f"ground:{side}:{n}", "Opening grounds", f"{side} ground {n} ({g.issue_id})", [g.ground], g.source_paras
            )
    for finding in truth.issue_findings:
        add(
            f"finding:{finding.issue_id}",
            "Sealed findings",
            f"{finding.issue_id}: favours {finding.favours} ({finding.driver})",
            [finding.finding, f"reasoning: {finding.reasoning}", f"test: {finding.test_applied}"],
            finding.source_paras,
        )
    end = truth.conclusion
    add(
        "conclusion",
        "Sealed findings",
        f"Conclusion: {end.disposition}, overall {end.overall_favours}",
        [*(f"relief ({r.sought_by}): {r.relief} -> {r.outcome}" for r in end.reliefs), *end.directions],
        [],
    )
    return page
