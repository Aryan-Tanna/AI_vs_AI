"""A bench verdict through the real MongoDB (D-070): recorded by the orchestrator only, `winner` and `aggregate` derived
from it, and ground truth still sealed until it is recorded.

Run with: pytest --run-integration -m integration
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import pytest

from lexarena.judges.bench import decide_bench
from lexarena.schemas.session import SessionState, ThemisGlobalReport
from lexarena.secrets import SecretStore
from lexarena.storage.errors import SealedError, StateTransitionError
from lexarena.storage.factory import SealedProcess, SessionProcess
from lexarena.storage.mongo import Namespace
from lexarena.storage.policy import Principal, Role
from lexarena.storage.sessions import SessionRepository
from tests import builders
from tests.conftest import ENV_FILE, SEALED_ENV_FILE
from tests.test_judges_bench import CFG, ISSUES, judge

pytestmark = pytest.mark.integration

CASE = "TESTCASE_BENCH_0001"
REPORT = ThemisGlobalReport(consistency={}, rebuttal_depth={}, contradictions=[])


@pytest.fixture(scope="module")
def procs() -> Iterator[tuple[SessionProcess, SealedProcess]]:
    ns = Namespace(prefix=f"t{uuid.uuid4().hex[:8]}_")
    session = SessionProcess(SecretStore(env_file=[ENV_FILE], environ={}), ns)
    sealed = SealedProcess(SecretStore(env_file=[ENV_FILE, SEALED_ENV_FILE], environ={}), ns)
    clerk = sealed.clerk()
    clerk.cases.put(builders.case(CASE))
    clerk.ground_truth.put(builders.ground_truth(CASE, "<sentinel>"))
    yield session, sealed
    for db in (session._app_db, sealed._sealed_db):
        for name in db.list_collection_names():
            if name.startswith(ns.prefix):
                db.drop_collection(name)
    session.close()
    sealed.close()


def _started(session: SessionProcess) -> str:
    sid = f"S_{uuid.uuid4().hex[:8]}"
    orch = session.orchestrator().sessions
    orch.create(builders.session(sid, CASE))
    orch.start(sid)
    return sid


def test_bench_verdict_round_trips_and_unseals(procs: tuple[SessionProcess, SealedProcess]) -> None:
    session, sealed = procs
    sid = _started(session)
    decisions = [
        judge("TEXTUALIST", "PETITIONER"),
        judge("PURPOSIVIST", "PETITIONER"),
        judge("PROCEDURALIST", "RESPONDENT"),
    ]
    verdict = decide_bench(decisions, ISSUES, CFG)
    with pytest.raises(SealedError):
        sealed.evaluator().ground_truth.get(CASE, session_id=sid)
    stored = session.orchestrator().sessions.record_bench_verdict(
        sid, decisions=decisions, bench=verdict, themis_global=REPORT
    )
    assert stored.state == SessionState.VERDICT_RECORDED and stored.winner == "PETITIONER"
    assert stored.aggregate is not None and verdict.advocacy is not None
    assert verdict.advocacy["PETITIONER"] == stored.aggregate.PETITIONER
    reread = sealed.evaluator().sessions.get(sid)
    assert reread.bench == verdict and reread.judge_decisions == decisions
    assert sealed.evaluator().ground_truth.get(CASE, session_id=sid).id == CASE


def test_unstable_bench_is_recorded_as_unstable(procs: tuple[SessionProcess, SealedProcess]) -> None:
    session, _ = procs
    sid = _started(session)
    decisions = [judge("TEXTUALIST", "PETITIONER"), judge("PURPOSIVIST", "RESPONDENT")]
    verdict = decide_bench(decisions, ISSUES, CFG)
    stored = session.orchestrator().sessions.record_bench_verdict(
        sid, decisions=decisions, bench=verdict, themis_global=REPORT
    )
    assert (stored.winner, stored.bench and stored.bench.unstable_reason) == ("UNSTABLE", "UNBROKEN_TIE")


def test_only_the_orchestrator_records_the_bench(procs: tuple[SessionProcess, SealedProcess]) -> None:
    session, _ = procs
    sid = _started(session)
    decisions = [judge("TEXTUALIST", "PETITIONER"), judge("PURPOSIVIST", "PETITIONER")]
    verdict = decide_bench(decisions, ISSUES, CFG)
    evaluator = SessionRepository(Principal(Role.EVALUATOR), session._app_db, session._ns)
    with pytest.raises(StateTransitionError):
        evaluator.record_bench_verdict(sid, decisions=decisions, bench=verdict, themis_global=REPORT)
