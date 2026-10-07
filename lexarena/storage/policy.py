"""Who may read and write each store: SPEC I1 and ARCHITECTURE §2 as one table.

Every repository checks this table on every call, in addition to being handed out only to the roles
that may hold it (`lexarena.storage.factory`). The ground-truth seal has a third layer underneath both:
its credentials never exist in a session process, and MongoDB refuses the shared app user (D-024).

Additions to SPEC I1, each needed by a documented job (D-035):
- the clerk reads the Law DB and precedents (statute-ID normalisation, overlap check, SPEC A/H);
- the orchestrator reads the full case (date cut-off and exclusion list are applied server-side) and both
  experience memories (it pins lessons at session start, ARCHITECTURE §4);
- the ingestion scripts read what they write (integrity checks).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import StrEnum
from typing import NoReturn

from lexarena.schemas.base import Side
from lexarena.storage.errors import AccessDeniedError

logger = logging.getLogger("lexarena.access")


class Role(StrEnum):
    CLERK = "CLERK"
    INGEST = "INGEST"
    ORCHESTRATOR = "ORCHESTRATOR"
    LAWYER = "LAWYER"
    THEMIS_LOCAL = "THEMIS_LOCAL"
    THEMIS_GLOBAL = "THEMIS_GLOBAL"
    JUDGE = "JUDGE"
    EVALUATOR = "EVALUATOR"
    REFLECTION = "REFLECTION"


SIDED_ROLES = frozenset({Role.LAWYER, Role.THEMIS_LOCAL})
OPTIONALLY_SIDED_ROLES = frozenset({Role.REFLECTION})


@dataclass(frozen=True)
class Principal:
    role: Role
    side: Side | None = None

    def __post_init__(self) -> None:
        if self.role in SIDED_ROLES and self.side is None:
            raise ValueError(f"{self.role} acts for one side; give side")
        if self.side is not None and self.role not in SIDED_ROLES | OPTIONALLY_SIDED_ROLES:
            raise ValueError(f"{self.role} does not act for a side")

    def __str__(self) -> str:
        return f"{self.role}({self.side})" if self.side else str(self.role)


class Store(StrEnum):
    LAW_DB = "LAW_DB"
    TEMPORAL_OVERLAY = "TEMPORAL_OVERLAY"
    PREDICATE_REGISTRY = "PREDICATE_REGISTRY"
    PRECEDENTS = "PRECEDENTS"  # session roles: only through a ScopedPrecedentReader bound to one case (D-052)
    PRECEDENTS_UNSCOPED = "PRECEDENTS_UNSCOPED"  # reads that ignore any case's cut-off and exclusions
    CASE_AGENT_VIEW = "CASE_AGENT_VIEW"  # agent_view without simulation_date
    CASE_FULL = "CASE_FULL"  # whole cases document: build, split, simulation_date
    CASE_GROUND_TRUTH = "CASE_GROUND_TRUTH"
    PUBLISHED_TURNS = "PUBLISHED_TURNS"
    PRIVATE_TURNS = "PRIVATE_TURNS"
    SESSION_MEMORY = "SESSION_MEMORY"
    LAWYER_MEMORY = "LAWYER_MEMORY"
    JUDGE_MEMORY = "JUDGE_MEMORY"
    SESSIONS = "SESSIONS"


class Op(StrEnum):
    READ = "READ"
    WRITE = "WRITE"


class Scope(StrEnum):
    ANY = "ANY"
    OWN_SIDE = "OWN_SIDE"  # principal.side must equal the data's side
    AFTER_VERDICT = "AFTER_VERDICT"  # the session must be in an unsealed state
    OWN_SIDE_AFTER_VERDICT = "OWN_SIDE_AFTER_VERDICT"


R = Role
_SESSION_READERS = (R.LAWYER, R.THEMIS_LOCAL, R.THEMIS_GLOBAL, R.JUDGE)
_KNOWLEDGE_READERS = {r: Scope.ANY for r in (*_SESSION_READERS, R.REFLECTION, R.ORCHESTRATOR, R.CLERK, R.INGEST)}

POLICY: dict[Store, dict[Op, dict[Role, Scope]]] = {
    Store.LAW_DB: {Op.READ: _KNOWLEDGE_READERS, Op.WRITE: {R.INGEST: Scope.ANY}},
    Store.TEMPORAL_OVERLAY: {Op.READ: _KNOWLEDGE_READERS, Op.WRITE: {R.INGEST: Scope.ANY}},
    Store.PREDICATE_REGISTRY: {Op.READ: _KNOWLEDGE_READERS, Op.WRITE: {R.INGEST: Scope.ANY}},
    Store.PRECEDENTS: {Op.READ: _KNOWLEDGE_READERS, Op.WRITE: {R.INGEST: Scope.ANY}},
    Store.PRECEDENTS_UNSCOPED: {
        Op.READ: {r: Scope.ANY for r in (R.INGEST, R.ORCHESTRATOR, R.CLERK)},
        Op.WRITE: {},
    },
    Store.CASE_AGENT_VIEW: {
        Op.READ: {r: Scope.ANY for r in (*_SESSION_READERS, R.ORCHESTRATOR, R.CLERK, R.EVALUATOR, R.REFLECTION)},
        Op.WRITE: {R.CLERK: Scope.ANY},
    },
    Store.CASE_FULL: {
        Op.READ: {r: Scope.ANY for r in (R.ORCHESTRATOR, R.CLERK, R.EVALUATOR, R.REFLECTION)},
        Op.WRITE: {R.CLERK: Scope.ANY},
    },
    Store.CASE_GROUND_TRUTH: {
        Op.READ: {R.EVALUATOR: Scope.AFTER_VERDICT, R.REFLECTION: Scope.AFTER_VERDICT},
        Op.WRITE: {R.CLERK: Scope.ANY},
    },
    Store.PUBLISHED_TURNS: {
        Op.READ: {r: Scope.ANY for r in (*_SESSION_READERS, R.ORCHESTRATOR, R.EVALUATOR, R.REFLECTION)},
        Op.WRITE: {R.ORCHESTRATOR: Scope.ANY},
    },
    Store.PRIVATE_TURNS: {
        Op.READ: {R.REFLECTION: Scope.OWN_SIDE_AFTER_VERDICT},
        Op.WRITE: {R.THEMIS_LOCAL: Scope.OWN_SIDE},
    },
    Store.SESSION_MEMORY: {
        Op.READ: {R.LAWYER: Scope.OWN_SIDE, R.THEMIS_LOCAL: Scope.OWN_SIDE},
        Op.WRITE: {R.LAWYER: Scope.OWN_SIDE},
    },
    Store.LAWYER_MEMORY: {
        # Party-status matching is applied by the lesson query (Step 12), on top of this rule.
        Op.READ: {R.LAWYER: Scope.ANY, R.ORCHESTRATOR: Scope.ANY},
        Op.WRITE: {R.REFLECTION: Scope.ANY},
    },
    Store.JUDGE_MEMORY: {
        Op.READ: {R.JUDGE: Scope.ANY, R.ORCHESTRATOR: Scope.ANY},
        Op.WRITE: {R.REFLECTION: Scope.ANY},
    },
    Store.SESSIONS: {
        Op.READ: {r: Scope.ANY for r in (R.ORCHESTRATOR, R.EVALUATOR, R.REFLECTION)},
        Op.WRITE: {r: Scope.ANY for r in (R.ORCHESTRATOR, R.EVALUATOR, R.REFLECTION)},
    },
}


def require(principal: Principal, store: Store, op: Op, *, data_side: Side | None = None) -> Scope:
    """Raise AccessDeniedError unless the table allows this; return the scope the caller must still honour.

    Side conditions are checked here when `data_side` is given. The verdict condition depends on the
    session's stored state, so the repository checks it and this returns the scope to tell it to.
    """
    scope = POLICY[store][op].get(principal.role)
    if scope is None:
        _deny(principal, store, op, "role not allowed")
    if scope in (Scope.OWN_SIDE, Scope.OWN_SIDE_AFTER_VERDICT) and (
        principal.side is None or data_side is None or principal.side != data_side
    ):
        _deny(principal, store, op, f"data belongs to {data_side}")
    return scope


def _deny(principal: Principal, store: Store, op: Op, reason: str) -> NoReturn:
    logger.warning("access denied: %s %s %s (%s)", principal, op, store, reason)
    raise AccessDeniedError(f"{principal} may not {op} {store}: {reason}")
