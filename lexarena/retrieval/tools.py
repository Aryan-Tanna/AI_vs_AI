"""Agent retrieval tools (BUILD_PLAN Step 5; SPEC B1, B2, B5, B7, D5; D-052).

Lawyers search by meaning: `find_similar_cases` on the facts multivector (symmetric, no query prefix) and
`find_authority` on the ratio vector (asymmetric, the model's query instruction prefixed to the query only).
Statutes are optional: a lawyer who names none searches the whole scoped DB; named statutes are resolved to
Law DB IDs by the same rules as ingestion, and those that resolve to none are reported back, not guessed.

The case's date cut-off and exclusion list live in the reader, fixed by the orchestrator. No tool takes a
date, cut-off or exclusion argument, so no agent can widen its own scope. `tools_for` hands each role only the
tools SPEC D5 and I3 give it: verifiers and judges fetch by ID, they do not search.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol

from lexarena.embedding import Embedder
from lexarena.schemas.case import AgentCaseView
from lexarena.schemas.retrieval import PrecedentView, RecordItemResult, SearchResult
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


class RetrievalTools:
    def __init__(
        self,
        *,
        reader: PrecedentReader,
        case: AgentCaseView,
        embedder: Embedder,
        known_statutes: set[str],
        aliases: StatuteAliasTable,
        top_k: int,
        query_instruction: str,
    ) -> None:
        self._reader = reader
        self._case = case
        self._embedder = embedder
        self._known = known_statutes
        self._aliases = aliases
        self._top_k = top_k
        self._instruction = query_instruction

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

    def _search(self, using: str, query: list[float] | list[list[float]], statutes: list[str] | None) -> SearchResult:
        law_ids, ignored = self._statutes(statutes)
        if statutes and not law_ids:
            return SearchResult(hits=[], statute_filter=[], ignored_statutes=ignored)
        hits = self._reader.search(using, query, law_ids, self._top_k)
        return SearchResult(
            hits=[PrecedentView.from_payload(p, score) for p, score in hits],
            statute_filter=law_ids,
            ignored_statutes=ignored,
        )

    def find_similar_cases(self, facts_text: str, statutes: list[str] | None = None) -> SearchResult:
        """Precedents whose material facts resemble `facts_text`, optionally only those citing `statutes`."""
        [vector] = self._embedder.embed([facts_text])
        return self._search(FACTS, [vector], statutes)

    def find_authority(self, proposition: str, statutes: list[str] | None = None) -> SearchResult:
        """Precedents whose legal rule (ratio parts 1 to 3) supports or bears on `proposition`."""
        [vector] = self._embedder.embed([self._instruction + proposition])
        return self._search(RATIO, vector, statutes)

    def get_precedent(self, precedent_uid: str) -> PrecedentView | None:
        """One precedent by its `precedent_uid`; None if unknown, decided too late, or excluded for this case."""
        payload = self._reader.get(precedent_uid)
        return PrecedentView.from_payload(payload) if payload is not None else None

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


def tools_for(role: Role, tools: RetrievalTools) -> dict[str, Callable[..., Any]]:
    """The callables one role may use; any other role gets none (PermissionError)."""
    names = TOOLS_BY_ROLE.get(role)
    if names is None:
        raise PermissionError(f"{role} has no retrieval tools")
    return {name: getattr(tools, name) for name in names}
