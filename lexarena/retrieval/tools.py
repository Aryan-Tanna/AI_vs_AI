"""Agent retrieval tools (BUILD_PLAN Step 5; SPEC B1, B2, B5, B7, D5; D-052, D-055).

Lawyers search by meaning: `find_similar_cases` on the facts multivector (symmetric, no query prefix) and
`find_authority` on the ratio vector (asymmetric, the model's query instruction prefixed to the query only).
Statutes are optional: a lawyer who names none searches the whole scoped DB; named statutes are resolved to
Law DB IDs by the same rules as ingestion, and those that resolve to none are reported back, not guessed.

Compact and fast (D-055): a search fetches `candidate_pool` hits, a cross-encoder re-scores each hit's passages
(facts sections, or ratio parts 1 to 3) against the raw query, and the best `top_k` come back as cards: the
precedent's rule and the passage that matched, each capped at `card_text_tokens`. Full text is fetched by ID,
one part at a time, so a search costs a few hundred tokens instead of thousands.

The case's date cut-off and exclusion list live in the reader, fixed by the orchestrator. No tool takes a
date, cut-off or exclusion argument, so no agent can widen its own scope. `tools_for` hands each role only the
tools SPEC D5 and I3 give it: verifiers and judges fetch by ID, they do not search.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from typing import Any, Protocol, get_args

from lexarena.embedding import Embedder, token_windows
from lexarena.precedent_text import core_rule, facts_sections, ratio_parts
from lexarena.rerank import Reranker
from lexarena.schemas.case import AgentCaseView
from lexarena.schemas.retrieval import (
    PrecedentCard,
    PrecedentExcerpt,
    PrecedentPart,
    PrecedentView,
    RecordItemResult,
    SearchResult,
)
from lexarena.schemas.statute_alias import StatuteAliasTable
from lexarena.statute_ids import resolve_statute_id
from lexarena.storage.policy import Role
from lexarena.storage.precedents import FACTS, RATIO


class PrecedentReader(Protocol):
    def search(
        self, using: str, query: list[float] | list[list[float]], statutes: list[str], limit: int
    ) -> list[tuple[dict[str, Any], float]]: ...

    def get(self, precedent_uid: str) -> dict[str, Any] | None: ...


SEARCH_TOOLS = ("find_similar_cases", "find_authority")
FETCH_TOOLS = ("get_precedent", "get_record_item")
TOOLS_BY_ROLE: dict[Role, tuple[str, ...]] = {
    Role.LAWYER: (*SEARCH_TOOLS, *FETCH_TOOLS),
    Role.THEMIS_LOCAL: FETCH_TOOLS,  # SPEC D5: layer 2 verifies by ID
    Role.THEMIS_GLOBAL: FETCH_TOOLS,
    Role.JUDGE: FETCH_TOOLS,  # SPEC I3: judges get read-only fetch tools, no open search
}
PART_FIELDS: dict[str, tuple[str, ...]] = {
    "ratio": ("ratio_decidendi",),
    "facts": ("material_facts",),
    "issues": ("legal_issues",),
    "order": ("final_order", "operative_order"),
    "summary": ("summary",),
}
CUT_MARK = "…"


class RetrievalTools:
    def __init__(
        self,
        *,
        reader: PrecedentReader,
        case: AgentCaseView,
        embedder: Embedder,
        reranker: Reranker | None,
        known_statutes: set[str],
        aliases: StatuteAliasTable,
        top_k: int,
        candidate_pool: int,
        card_text_tokens: int,
        query_instruction: str,
    ) -> None:
        self._reader = reader
        self._case = case
        self._embedder = embedder
        self._reranker = reranker
        self._known = known_statutes
        self._aliases = aliases
        self._top_k = top_k
        self._pool = candidate_pool
        self._card_tokens = card_text_tokens
        self._instruction = query_instruction

    # ------------------------------------------------------------ helpers

    def _statutes(self, given: list[str] | None) -> tuple[list[str], list[str]]:
        found: list[str] = []
        ignored: list[str] = []
        for cited in given or []:
            match, _ = resolve_statute_id(cited, self._known, self._aliases)
            if match is None:
                ignored.append(cited)
            elif match not in found:
                found.append(match)
        return found, ignored

    def _cap(self, text: str) -> str:
        first = token_windows(text, self._embedder.count_tokens, self._card_tokens)[0] if text else ""
        return first if first == text else first + CUT_MARK

    def _card(self, payload: dict[str, Any], matched: str, score: float, reranked: bool) -> PrecedentCard:
        rule = core_rule(payload["ratio_decidendi"])
        return PrecedentCard(
            precedent_uid=payload["precedent_uid"],
            precedent_id=payload["precedent_id"],
            case_title=payload["case_title"],
            forum=payload["forum"],
            decision_date=payload["decision_date"],
            final_order=payload["final_order"],
            statutes=payload["statutes_normalized"],
            rule=self._cap(rule),
            matched="" if matched == rule else self._cap(matched),  # never spend tokens on the rule twice
            score=score,
            score_kind="RERANKER" if reranked else "VECTOR",
        )

    def _nearest_passages(self, query_vector: list[float], groups: list[list[str]]) -> list[str]:
        flat = [text for group in groups for text in group]
        vectors = iter(self._embedder.embed(flat) if flat else [])
        best: list[str] = []
        for group in groups:
            scored = [(_cosine(query_vector, next(vectors)), text) for text in group]
            best.append(max(scored, default=(0.0, ""), key=lambda x: x[0])[1])
        return best

    def _search(
        self,
        using: str,
        query: list[float] | list[list[float]],
        query_text: str,
        passages_of: Callable[[dict[str, Any]], list[str]],
        statutes: list[str] | None,
    ) -> SearchResult:
        law_ids, ignored = self._statutes(statutes)
        if statutes and not law_ids:
            return SearchResult(hits=[], statute_filter=[], ignored_statutes=ignored)
        if self._reranker is None:
            hits = self._reader.search(using, query, law_ids, self._top_k)
            if using == FACTS:  # which section matched: the one nearest the query, from one small embedding batch
                matched = self._nearest_passages(query[0], [passages_of(p) for p, _ in hits])  # type: ignore[arg-type]
            else:  # the ratio vector covers parts 1 to 3 together; the card's rule already shows part 1
                matched = [""] * len(hits)
            cards = [self._card(p, m, s, False) for (p, s), m in zip(hits, matched, strict=True)]
            return SearchResult(hits=cards, statute_filter=law_ids, ignored_statutes=ignored)

        candidates = self._reader.search(using, query, law_ids, self._pool)
        passages = [passages_of(p) for p, _ in candidates]
        flat = [text for group in passages for text in group]
        scores = iter(self._reranker.score(query_text, flat))  # one batch for every candidate's passages
        ranked: list[tuple[float, float, int, str]] = []
        for i, group in enumerate(passages):
            scored = [(next(scores), text) for text in group]
            best_score, best_text = max(scored, default=(float("-inf"), ""), key=lambda x: x[0])
            ranked.append((-best_score, -candidates[i][1], i, best_text))
        ranked.sort()  # reranker score, then vector score (both descending), then vector order
        cards = [self._card(candidates[i][0], text, -neg, True) for neg, _, i, text in ranked[: self._top_k]]
        return SearchResult(hits=cards, statute_filter=law_ids, ignored_statutes=ignored)

    # ------------------------------------------------------------ tools

    def find_similar_cases(self, facts_text: str, statutes: list[str] | None = None) -> SearchResult:
        """Precedents whose material facts resemble `facts_text`, optionally only those citing `statutes`."""
        [vector] = self._embedder.embed([facts_text])
        return self._search(FACTS, [vector], facts_text, lambda p: facts_sections(p["material_facts"]), statutes)

    def find_authority(self, proposition: str, statutes: list[str] | None = None) -> SearchResult:
        """Precedents whose legal rule (ratio parts 1 to 3) supports or bears on `proposition`."""
        [vector] = self._embedder.embed([self._instruction + proposition])
        return self._search(RATIO, vector, proposition, lambda p: ratio_parts(p["ratio_decidendi"]), statutes)

    def get_precedent(
        self, precedent_uid: str, part: PrecedentPart = "ratio"
    ) -> PrecedentExcerpt | PrecedentView | None:
        """One part of a precedent by its `precedent_uid` (ratio, facts, issues, order, summary, or all); None if
        unknown, decided too late, or excluded for this case."""
        if part not in get_args(PrecedentPart):
            raise ValueError(f"unknown part {part!r}; use one of {get_args(PrecedentPart)}")
        payload = self._reader.get(precedent_uid)
        if payload is None:
            return None
        if part == "all":
            return PrecedentView.from_payload(payload)
        return PrecedentExcerpt(
            precedent_uid=payload["precedent_uid"],
            precedent_id=payload["precedent_id"],
            case_title=payload["case_title"],
            decision_date=payload["decision_date"],
            part=part,
            text="\n".join(payload[f] for f in PART_FIELDS[part]),
        )

    def get_record_item(self, item_id: str) -> RecordItemResult | None:
        """A stipulated fact (F), contested fact (C), exhibit (EX) or amount (AM) of this case's record."""
        record = self._case.record
        for kind, items, key in (
            ("STIPULATED_FACT", record.stipulated_facts, "fact_id"),
            ("CONTESTED_FACT", record.contested_facts, "fact_id"),
            ("EXHIBIT", record.exhibits, "exhibit_id"),
            ("AMOUNT", record.amounts, "amount_id"),
        ):
            for item in items:
                if getattr(item, key) == item_id:
                    return RecordItemResult.model_validate({"kind": kind, "item": item})
        return None


def _cosine(a: list[float], b: list[float]) -> float:
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return sum(x * y for x, y in zip(a, b, strict=True)) / norm if norm else 0.0


def tools_for(role: Role, tools: RetrievalTools) -> dict[str, Callable[..., Any]]:
    """The callables one role may use; any other role gets none (PermissionError)."""
    names = TOOLS_BY_ROLE.get(role)
    if names is None:
        raise PermissionError(f"{role} has no retrieval tools")
    return {name: getattr(tools, name) for name in names}
