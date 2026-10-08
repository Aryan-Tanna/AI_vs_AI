"""The access table matches SPEC I1 and ARCHITECTURE §2. The expectations below are copied from the
"Never read by" and "Written by" columns independently of `policy.POLICY`, so an edit to the table that
breaks the SPEC fails here."""

from __future__ import annotations

import pytest

from lexarena.storage.errors import AccessDeniedError
from lexarena.storage.policy import POLICY, Op, Principal, Role, Scope, Store, require

R = Role
SESSION_ROLES = {R.LAWYER, R.THEMIS_LOCAL, R.THEMIS_GLOBAL, R.JUDGE}

# SPEC I1 "Never read by".
NEVER_READ_BY: dict[Store, set[Role]] = {
    Store.CASE_GROUND_TRUTH: SESSION_ROLES | {R.ORCHESTRATOR, R.CLERK, R.INGEST},
    Store.PRIVATE_TURNS: SESSION_ROLES | {R.ORCHESTRATOR, R.EVALUATOR, R.CLERK, R.INGEST},
    Store.SESSION_MEMORY: {R.THEMIS_GLOBAL, R.JUDGE, R.ORCHESTRATOR, R.EVALUATOR, R.REFLECTION, R.CLERK},
    Store.LAWYER_MEMORY: {R.JUDGE, R.THEMIS_LOCAL, R.THEMIS_GLOBAL},
    Store.JUDGE_MEMORY: {R.LAWYER, R.THEMIS_LOCAL, R.THEMIS_GLOBAL},
    Store.SESSIONS: SESSION_ROLES,
    Store.CASE_FULL: SESSION_ROLES,  # D-035: build, split and simulation_date never reach a prompt
    Store.PRECEDENTS_UNSCOPED: SESSION_ROLES,  # D-052: session roles read precedents only through a CaseScope
    Store.JUDGMENT_TEXT: SESSION_ROLES | {R.ORCHESTRATOR, R.CLERK, R.INGEST},  # D-056: holds the court's reasoning
}

# SPEC I1 "Written by".
ONLY_WRITTEN_BY: dict[Store, set[Role]] = {
    Store.LAW_DB: {R.INGEST},
    Store.TEMPORAL_OVERLAY: {R.INGEST},
    Store.PREDICATE_REGISTRY: {R.INGEST},
    Store.PRECEDENTS: {R.INGEST},
    Store.PRECEDENTS_UNSCOPED: set(),  # a read-only view; writes go through PRECEDENTS
    Store.JUDGMENT_TEXT: {R.CLERK},
    Store.CASE_FULL: {R.CLERK},
    Store.CASE_AGENT_VIEW: {R.CLERK},
    Store.CASE_GROUND_TRUTH: {R.CLERK},
    Store.PUBLISHED_TURNS: {R.ORCHESTRATOR},
    Store.PRIVATE_TURNS: {R.THEMIS_LOCAL},
    Store.SESSION_MEMORY: {R.LAWYER},
    Store.LAWYER_MEMORY: {R.REFLECTION},
    Store.JUDGE_MEMORY: {R.REFLECTION},
    Store.SESSIONS: {R.ORCHESTRATOR, R.EVALUATOR, R.REFLECTION},
}


def test_every_store_has_a_rule_for_both_operations() -> None:
    assert set(POLICY) == set(Store)
    for store, ops in POLICY.items():
        assert set(ops) == set(Op), store


@pytest.mark.parametrize("store", list(NEVER_READ_BY))
def test_never_read_by(store: Store) -> None:
    assert set(POLICY[store][Op.READ]) & NEVER_READ_BY[store] == set()


@pytest.mark.parametrize("store", list(ONLY_WRITTEN_BY))
def test_only_written_by(store: Store) -> None:
    assert set(POLICY[store][Op.WRITE]) == ONLY_WRITTEN_BY[store]


def test_ground_truth_reads_wait_for_the_verdict_except_the_owners_review_before_any_session() -> None:
    """D-056 (Q-019 option A): REVIEW is the only reader before the verdict, and only before any session exists."""
    for store in (Store.CASE_GROUND_TRUTH, Store.JUDGMENT_TEXT):
        readers = POLICY[store][Op.READ]
        assert readers[R.REVIEW] == Scope.BEFORE_FIRST_SESSION, store
        assert {r: s for r, s in readers.items() if r != R.REVIEW} == {
            R.EVALUATOR: Scope.AFTER_VERDICT,
            R.REFLECTION: Scope.AFTER_VERDICT,
        }, store


def test_review_is_read_only_and_reads_nothing_of_a_session() -> None:
    writes = {store for store, ops in POLICY.items() if R.REVIEW in ops[Op.WRITE]}
    assert writes == set()
    session_data = (Store.PUBLISHED_TURNS, Store.PRIVATE_TURNS, Store.SESSION_MEMORY, Store.SESSIONS)
    assert all(R.REVIEW not in POLICY[s][Op.READ] for s in session_data)
    assert set(POLICY[Store.PRIVATE_TURNS][Op.READ].values()) == {Scope.OWN_SIDE_AFTER_VERDICT}


def test_sided_scopes_compare_sides() -> None:
    p_reflection = Principal(R.REFLECTION, "PETITIONER")
    assert require(p_reflection, Store.PRIVATE_TURNS, Op.READ, data_side="PETITIONER") == Scope.OWN_SIDE_AFTER_VERDICT
    with pytest.raises(AccessDeniedError):
        require(p_reflection, Store.PRIVATE_TURNS, Op.READ, data_side="RESPONDENT")
    with pytest.raises(AccessDeniedError):
        require(Principal(R.REFLECTION), Store.PRIVATE_TURNS, Op.READ, data_side="PETITIONER")


def test_principal_side_rules() -> None:
    with pytest.raises(ValueError):
        Principal(R.LAWYER)
    with pytest.raises(ValueError):
        Principal(R.JUDGE, "PETITIONER")
    assert str(Principal(R.THEMIS_LOCAL, "RESPONDENT")) == "THEMIS_LOCAL(RESPONDENT)"
