"""BUILD_PLAN Step 1 acceptance: nobody but the evaluator and reflection reads ground truth, and only after
VERDICT_RECORDED; nobody reads the other side's private data. Runs against the real MongoDB.

Run with: pytest --run-integration -m integration
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterator
from dataclasses import dataclass, fields
from typing import Any

import pytest
from pymongo.errors import DuplicateKeyError

from lexarena.schemas.base import Side
from lexarena.schemas.session import Aggregate, Evaluation, SessionState, ThemisGlobalReport
from lexarena.secrets import SecretStore
from lexarena.storage.errors import AccessDeniedError, SealedError, StateTransitionError
from lexarena.storage.factory import SealedProcess, SessionProcess
from lexarena.storage.ground_truth import GroundTruthRepository
from lexarena.storage.mongo import Namespace
from lexarena.storage.policy import Principal, Role
from lexarena.storage.precedents import PrecedentRepository, ScopedPrecedentReader
from lexarena.storage.sessions import SessionRepository
from lexarena.storage.transcript import PrivateTurnRepository
from tests import builders
from tests.builders import SCOPE
from tests.conftest import ENV_FILE, SEALED_ENV_FILE

pytestmark = pytest.mark.integration

P: Side = "PETITIONER"
D: Side = "RESPONDENT"
CASE = "TESTCASE_0001"
OTHER_CASE = "TESTCASE_0002"
SIM_DATE = "1999-12-31"  # literal-ok: sentinel simulation_date, distinct from every other placeholder date
GT_SENTINEL = f"SENTINEL_GT_{uuid.uuid4().hex}"
BUILD_SENTINEL = f"SENTINEL_BUILD_{uuid.uuid4().hex}"
PRIVATE_SENTINEL = f"SENTINEL_PRIVATE_{uuid.uuid4().hex}"

BARRED_FROM_GROUND_TRUTH = [
    Principal(Role.LAWYER, P),
    Principal(Role.LAWYER, D),
    Principal(Role.THEMIS_LOCAL, P),
    Principal(Role.THEMIS_LOCAL, D),
    Principal(Role.THEMIS_GLOBAL),
    Principal(Role.JUDGE),
    Principal(Role.ORCHESTRATOR),
    Principal(Role.CLERK),
]
GROUND_TRUTH_READERS = [Principal(Role.EVALUATOR), Principal(Role.REFLECTION), Principal(Role.REFLECTION, P)]


@dataclass
class World:
    session: SessionProcess
    sealed: SealedProcess
    ns: Namespace

    def new_session(self, case_id: str = CASE, state: SessionState = SessionState.CREATED) -> str:
        sid = f"S_{uuid.uuid4().hex[:8]}"
        orch = self.session.orchestrator().sessions
        orch.create(builders.session(sid, case_id))
        path = [SessionState.IN_PROGRESS, SessionState.VERDICT_RECORDED, SessionState.EVALUATED, SessionState.REFLECTED]
        if state == SessionState.ABORTED:
            orch.abort(sid)
            return sid
        for step in path:
            if state == SessionState.CREATED or path.index(step) > path.index(state):
                break
            self._advance(sid, step)
        return sid

    def _advance(self, sid: str, step: SessionState) -> None:
        orch = self.session.orchestrator().sessions
        if step == SessionState.IN_PROGRESS:
            orch.start(sid)
        elif step == SessionState.VERDICT_RECORDED:
            orch.record_verdict(
                sid,
                scorecards=[],
                aggregate=Aggregate(PETITIONER=0.5, RESPONDENT=0.5),
                winner="TIE",
                themis_global=ThemisGlobalReport(consistency={}, rebuttal_depth={}, contradictions=[]),
            )
        elif step == SessionState.EVALUATED:
            self.sealed.evaluator().sessions.record_evaluation(
                sid, Evaluation(winner_matches_real=None, issue_alignment=0.0)
            )
        elif step == SessionState.REFLECTED:
            self.sealed.reflection().sessions.record_lessons(sid, [])


@pytest.fixture(scope="module")
def world() -> Iterator[World]:
    ns = Namespace(prefix=f"t{uuid.uuid4().hex[:8]}_")
    session_proc = SessionProcess(SecretStore(env_file=[ENV_FILE], environ={}), ns)
    sealed_proc = SealedProcess(SecretStore(env_file=[ENV_FILE, SEALED_ENV_FILE], environ={}), ns)
    clerk = sealed_proc.clerk()
    for case_id in (CASE, OTHER_CASE):
        clerk.cases.put(builders.case(case_id, build_marker=BUILD_SENTINEL, date_marker=SIM_DATE))
        clerk.ground_truth.put(builders.ground_truth(case_id, GT_SENTINEL))
    w = World(session_proc, sealed_proc, ns)
    yield w
    for db in (session_proc._app_db, sealed_proc._sealed_db):
        for name in db.list_collection_names():
            if name.startswith(ns.prefix):
                db.drop_collection(name)
    session_proc.close()
    sealed_proc.close()


def _gt_repo(world: World, principal: Principal) -> GroundTruthRepository:
    # Built directly with a sealed handle the session process could never obtain, so this tests the
    # role and state layers on their own, independent of the credential layer.
    return GroundTruthRepository(principal, world.sealed._sealed_db, world.session._app_db, world.ns)


def _session_bundles(world: World, sid: str) -> dict[str, Any]:
    s = world.session
    return {
        "lawyer_P": s.lawyer(P, sid, SCOPE),
        "lawyer_D": s.lawyer(D, sid, SCOPE),
        "themis_local_P": s.themis_local(P, sid, SCOPE),
        "themis_local_D": s.themis_local(D, sid, SCOPE),
        "themis_global": s.themis_global(SCOPE),
        "judge": s.judge(SCOPE),
        "orchestrator": s.orchestrator(),
    }


# ---------------------------------------------------------------- ground truth: credential layer


def test_session_process_has_no_sealed_handle_and_no_ground_truth_repository(world: World) -> None:
    sid = world.new_session()
    assert not hasattr(world.session, "_sealed_db")
    for name, bundle in _session_bundles(world, sid).items():
        held = [getattr(bundle, f.name) for f in fields(bundle)]
        assert not any(isinstance(r, GroundTruthRepository) for r in held), name


def test_session_roles_read_precedents_only_through_the_case_scope(world: World) -> None:
    """D-052: each session-role bundle holds a reader bound to the scope it was given, never the open repository."""
    sid = world.new_session()
    for name, bundle in _session_bundles(world, sid).items():
        if name == "orchestrator":
            assert isinstance(bundle.precedents, PrecedentRepository)
            continue
        held = [getattr(bundle, f.name) for f in fields(bundle)]
        assert not any(isinstance(r, PrecedentRepository) for r in held), name
        assert isinstance(bundle.precedents, ScopedPrecedentReader), name
        assert bundle.precedents._scope == SCOPE, name


# ---------------------------------------------------------------- ground truth: role layer


@pytest.mark.parametrize("state", list(SessionState))
@pytest.mark.parametrize("principal", BARRED_FROM_GROUND_TRUTH, ids=str)
def test_barred_roles_never_read_ground_truth_in_any_state(
    world: World, principal: Principal, state: SessionState
) -> None:
    sid = world.new_session(state=state)
    with pytest.raises(AccessDeniedError):
        _gt_repo(world, principal).get(CASE, session_id=sid)


# ---------------------------------------------------------------- ground truth: state layer


@pytest.mark.parametrize("state", [SessionState.CREATED, SessionState.IN_PROGRESS, SessionState.ABORTED])
@pytest.mark.parametrize("principal", GROUND_TRUTH_READERS, ids=str)
def test_readers_refused_before_verdict(world: World, principal: Principal, state: SessionState) -> None:
    sid = world.new_session(state=state)
    with pytest.raises(SealedError):
        _gt_repo(world, principal).get(CASE, session_id=sid)


@pytest.mark.parametrize("state", [SessionState.VERDICT_RECORDED, SessionState.EVALUATED, SessionState.REFLECTED])
def test_evaluator_and_reflection_read_after_verdict(world: World, state: SessionState) -> None:
    sid = world.new_session(state=state)
    for stores in (world.sealed.evaluator(), world.sealed.reflection()):
        truth = stores.ground_truth.get(CASE, session_id=sid)
        assert truth.issue_findings[0].finding == GT_SENTINEL


def test_verdict_in_another_case_does_not_unseal(world: World) -> None:
    other_sid = world.new_session(case_id=OTHER_CASE, state=SessionState.VERDICT_RECORDED)
    with pytest.raises(SealedError):
        world.sealed.evaluator().ground_truth.get(CASE, session_id=other_sid)


# ---------------------------------------------------------------- nothing sealed reaches a session role


def test_session_reads_contain_no_sealed_or_build_values(world: World) -> None:
    sid = world.new_session(state=SessionState.IN_PROGRESS)
    world.session.orchestrator().transcript.publish(builders.published_turn(sid, CASE, 1, P))
    world.session.themis_local(P, sid, SCOPE).private_turns.put(
        builders.private_turn(sid, CASE, 1, P, PRIVATE_SENTINEL)
    )
    for name, bundle in _session_bundles(world, sid).items():
        if name == "orchestrator":
            continue  # reads the full case by design (date cut-off, exclusions); never prompts an LLM
        seen = json.dumps(
            [
                bundle.case.agent_view(CASE).model_dump(mode="json"),
                [t.model_dump(mode="json") for t in bundle.transcript.turns(sid)],
            ]
        )
        for marker in (GT_SENTINEL, BUILD_SENTINEL, PRIVATE_SENTINEL, SIM_DATE, '"split"', '"build"'):
            assert marker not in seen, f"{name} saw {marker}"
        assert "<argument text>" in seen  # positive control: the reads did return data


def test_agent_view_validation_fails_if_a_hidden_field_slips_through(world: World) -> None:
    from lexarena.schemas.case import AgentCaseView

    stored = world.sealed.clerk().cases  # clerk may read the full case
    doc = stored._col.find_one({"_id": CASE}, projection={"agent_view": True})
    assert doc is not None
    with pytest.raises(ValueError, match="simulation_date"):
        AgentCaseView.model_validate({**doc["agent_view"], "case_id": CASE})


# ---------------------------------------------------------------- the other side's private data


ALL_BUT_OWN_REFLECTION = [
    Principal(Role.LAWYER, P),
    Principal(Role.LAWYER, D),
    Principal(Role.THEMIS_LOCAL, P),
    Principal(Role.THEMIS_LOCAL, D),
    Principal(Role.THEMIS_GLOBAL),
    Principal(Role.JUDGE),
    Principal(Role.ORCHESTRATOR),
    Principal(Role.EVALUATOR),
    Principal(Role.CLERK),
    Principal(Role.REFLECTION),
    Principal(Role.REFLECTION, D),
]


@pytest.fixture(scope="module")
def private_session(world: World) -> str:
    sid = world.new_session(state=SessionState.IN_PROGRESS)
    world.session.themis_local(P, sid, SCOPE).private_turns.put(
        builders.private_turn(sid, CASE, 1, P, PRIVATE_SENTINEL)
    )
    world.session.orchestrator().sessions.record_verdict(
        sid,
        scorecards=[],
        aggregate=Aggregate(PETITIONER=0.5, RESPONDENT=0.5),
        winner="TIE",
        themis_global=ThemisGlobalReport(consistency={}, rebuttal_depth={}, contradictions=[]),
    )
    return sid


@pytest.mark.parametrize("principal", ALL_BUT_OWN_REFLECTION, ids=str)
def test_private_turns_refused_to_everyone_but_own_reflection(
    world: World, private_session: str, principal: Principal
) -> None:
    repo = PrivateTurnRepository(principal, world.session._app_db, world.ns)
    with pytest.raises(AccessDeniedError):
        repo.for_side(private_session, P)


def test_own_reflection_reads_private_turns_after_verdict_only(world: World, private_session: str) -> None:
    data = world.sealed.reflection(P).private_turns.for_side(private_session, P)
    assert data[0].themis_local.warnings[0].detail == PRIVATE_SENTINEL

    sid = world.new_session(state=SessionState.IN_PROGRESS)
    world.session.themis_local(P, sid, SCOPE).private_turns.put(
        builders.private_turn(sid, CASE, 1, P, PRIVATE_SENTINEL)
    )
    with pytest.raises(SealedError):
        world.sealed.reflection(P).private_turns.for_side(sid, P)


def test_themis_local_cannot_write_the_other_sides_private_data(world: World) -> None:
    sid = world.new_session(state=SessionState.IN_PROGRESS)
    with pytest.raises(AccessDeniedError):
        world.session.themis_local(D, sid, SCOPE).private_turns.put(builders.private_turn(sid, CASE, 1, P, "<x>"))


def test_private_write_cannot_overwrite_the_other_sides_document(world: World) -> None:
    sid = world.new_session(state=SessionState.IN_PROGRESS)
    world.session.themis_local(P, sid, SCOPE).private_turns.put(
        builders.private_turn(sid, CASE, 1, P, PRIVATE_SENTINEL)
    )
    with pytest.raises(DuplicateKeyError):
        world.session.themis_local(D, sid, SCOPE).private_turns.put(builders.private_turn(sid, CASE, 1, D, "<x>"))


def test_session_memory_is_per_side(world: World) -> None:
    sid = world.new_session()
    lawyer_p, lawyer_d = world.session.lawyer(P, sid, SCOPE), world.session.lawyer(D, sid, SCOPE)
    lawyer_p.memory.append(PRIVATE_SENTINEL)
    assert lawyer_d.memory.items() == []
    assert world.session.themis_local(D, sid, SCOPE).agent_memory.items() == []
    assert world.session.themis_local(P, sid, SCOPE).agent_memory.items() == [PRIVATE_SENTINEL]
    with pytest.raises(AccessDeniedError):
        world.session.themis_local(P, sid, SCOPE).agent_memory.append("<x>")


# ---------------------------------------------------------------- session state machine


def test_lawyer_cannot_touch_sessions(world: World) -> None:
    sid = world.new_session(state=SessionState.IN_PROGRESS)
    repo = SessionRepository(Principal(Role.LAWYER, P), world.session._app_db, world.ns)
    with pytest.raises(AccessDeniedError):
        repo.get(sid)
    with pytest.raises(AccessDeniedError):
        repo.record_verdict(
            sid,
            scorecards=[],
            aggregate=Aggregate(PETITIONER=1.0, RESPONDENT=0.0),
            winner="PETITIONER",
            themis_global=ThemisGlobalReport(consistency={}, rebuttal_depth={}, contradictions=[]),
        )


def test_state_cannot_skip_or_go_back(world: World) -> None:
    sid = world.new_session()
    report = ThemisGlobalReport(consistency={}, rebuttal_depth={}, contradictions=[])
    agg = Aggregate(PETITIONER=0.5, RESPONDENT=0.5)
    orch = world.session.orchestrator().sessions
    with pytest.raises(StateTransitionError):
        orch.record_verdict(sid, scorecards=[], aggregate=agg, winner="TIE", themis_global=report)
    orch.start(sid)
    with pytest.raises(StateTransitionError):  # the evaluator cannot record a verdict
        SessionRepository(Principal(Role.EVALUATOR), world.session._app_db, world.ns).record_verdict(
            sid, scorecards=[], aggregate=agg, winner="TIE", themis_global=report
        )
    orch.record_verdict(sid, scorecards=[], aggregate=agg, winner="TIE", themis_global=report)
    with pytest.raises(StateTransitionError):
        orch.record_verdict(sid, scorecards=[], aggregate=agg, winner="TIE", themis_global=report)
    with pytest.raises(StateTransitionError):
        orch.abort(sid)
    assert orch.get(sid).state == SessionState.VERDICT_RECORDED


def test_published_turns_are_immutable_and_orchestrator_only(world: World) -> None:
    sid = world.new_session(state=SessionState.IN_PROGRESS)
    turn = builders.published_turn(sid, CASE, 1, P)
    world.session.orchestrator().transcript.publish(turn)
    with pytest.raises(DuplicateKeyError):
        world.session.orchestrator().transcript.publish(turn)
    with pytest.raises(AccessDeniedError):
        world.session.lawyer(P, sid, SCOPE).transcript.publish(builders.published_turn(sid, CASE, 2, P))
