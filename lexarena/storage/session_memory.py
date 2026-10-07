"""In-session memory for each agent (SPEC I1: written by the agent, read by it and its own THEMIS-LOCAL,
never by the opponent or later sessions). In-process behind this interface, Redis optional (D-024 item 8).

A handle is bound to one session and one side when it is issued; there is no method that takes a side,
so code holding LEX-P's handle has no way to name LEX-D's memory.
"""

from __future__ import annotations

from collections import defaultdict

from lexarena.schemas.base import Side
from lexarena.storage.policy import Op, Principal, Store, require


class SessionMemoryHandle:
    def __init__(self, principal: Principal, session_id: str, side: Side, items: list[str]) -> None:
        self._principal = principal
        self._session_id = session_id
        self._side = side
        self._items = items

    def append(self, item: str) -> None:
        require(self._principal, Store.SESSION_MEMORY, Op.WRITE, data_side=self._side)
        self._items.append(item)

    def items(self) -> list[str]:
        require(self._principal, Store.SESSION_MEMORY, Op.READ, data_side=self._side)
        return list(self._items)


class InProcessSessionMemory:
    def __init__(self) -> None:
        self._store: defaultdict[tuple[str, Side], list[str]] = defaultdict(list)

    def handle(self, principal: Principal, session_id: str) -> SessionMemoryHandle:
        if principal.side is None:
            raise ValueError(f"{principal} has no side, so it has no session memory")
        require(principal, Store.SESSION_MEMORY, Op.READ, data_side=principal.side)
        return SessionMemoryHandle(principal, session_id, principal.side, self._store[(session_id, principal.side)])

    def clear_session(self, session_id: str) -> None:
        """Called by the orchestrator when a session ends (SPEC I1: cleared at the end)."""
        for key in [k for k in self._store if k[0] == session_id]:
            del self._store[key]
