"""Second-family entailment of the agent view against its sources (SPEC I3-8; D-056 point 4).

Every stipulated fact, contested fact (both versions), exhibit (its known contents) and opening ground is checked
by the clerk's secondary model, a different model family from the extractor, against only the text it cites. Items
are batched within `clerk.entailment_batch_chars` so each request fits the secondary provider's input limit.
NOT_SUPPORTED blocks the case; PARTLY is flagged for review; a missing or duplicated verdict is an error, never a
pass.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from lexarena.llm.client import LLMClient
from lexarena.prompts import PromptStore
from lexarena.schemas.case import AgentView, ExtractionFlag
from lexarena.schemas.clerk import EntailmentResult
from lexarena.schemas.config import AppConfig

ROLE = "clerk_secondary"


class EntailmentError(ValueError):
    """The verifier did not give exactly one verdict per item."""


@dataclass(frozen=True)
class Item:
    item_id: str
    claim: str
    sources: str

    def render(self) -> str:
        return f"[{self.item_id}]\nItem: {self.claim}\nSources:\n{self.sources}"


def entailment_items(view: AgentView, sources: dict[str, str]) -> list[Item]:
    def src(ids: list[str]) -> str:
        return "\n".join(f"({s}) {sources[s]}" for s in ids if s in sources)

    r = view.record
    items = [Item(f.fact_id, f.text, src(f.source_paras)) for f in r.stipulated_facts]
    items += [
        Item(
            c.fact_id,
            f"Disputed point: {c.question} PETITIONER's version: {c.petitioner_version} "
            f"RESPONDENT's version: {c.respondent_version}",
            src(c.source_paras),
        )
        for c in r.contested_facts
    ]
    items += [
        Item(
            e.exhibit_id,
            f"Document {e.title!r}, filed by {e.filed_by}, contains: {'; '.join(e.known_contents)}",
            src(e.source_paras),
        )
        for e in r.exhibits
    ]
    for side in ("PETITIONER", "RESPONDENT"):
        grounds = view.opening_positions.for_side(side)
        items += [
            Item(f"{side}-G{i}", f"{side}'s ground: {g.ground}", src(g.source_paras)) for i, g in enumerate(grounds, 1)
        ]
    return items


def _batches(items: list[Item], budget: int) -> list[list[Item]]:
    batches: list[list[Item]] = []
    current: list[Item] = []
    size = 0
    for item in items:
        n = len(item.render())
        if current and size + n > budget:
            batches.append(current)
            current, size = [], 0
        current.append(item)
        size += n
    if current:
        batches.append(current)
    return batches


def check_entailment(
    llm: LLMClient,
    prompts: PromptStore,
    cfg: AppConfig,
    view: AgentView,
    sources: dict[str, str],
    *,
    session_id: str,
) -> tuple[list[str], list[ExtractionFlag]]:
    ref = cfg.prompts.clerk_entailment
    problems: list[str] = []
    flags: list[ExtractionFlag] = []
    for batch in _batches(entailment_items(view, sources), cfg.clerk.entailment_batch_chars):
        prompt = prompts.render(ref.id, ref.version, items="\n\n".join(i.render() for i in batch))
        result = llm.complete_json(role=ROLE, user=prompt, schema=EntailmentResult, session_id=session_id).value
        got = Counter(v.item_id for v in result.verdicts)
        wanted = [i.item_id for i in batch]
        if any(got[i] != 1 for i in wanted) or set(got) - set(wanted):
            raise EntailmentError(f"verdicts {dict(got)} do not match items {wanted}")
        for v in result.verdicts:
            if v.verdict == "NOT_SUPPORTED":
                problems.append(f"{v.item_id} is not supported by its sources ({v.reason})")
            elif v.verdict == "PARTLY":
                flags.append(
                    ExtractionFlag(
                        code="ENTAILMENT_PARTLY",
                        detail=f"{v.item_id}: {v.reason}",
                        resolution="kept; review the item against its source paragraphs",
                    )
                )
    return problems, flags
