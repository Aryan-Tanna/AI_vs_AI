"""The evaluator against the real MongoDB (BUILD_PLAN Step 12; non-negotiable 6; D-072): ground truth unseals only
after the bench verdict, the evaluation moves the session to EVALUATED, and a session without a bench is refused.

Run with: pytest --run-integration -m integration
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import pytest

from lexarena.evaluator.evaluate import NotEvaluableError, evaluate_session
from lexarena.judges.bench import decide_bench
from lexarena.schemas.session import Aggregate, SessionState, ThemisGlobalReport
from lexarena.secrets import SecretStore
from lexarena.storage.errors import SealedError
from lexarena.storage.factory import SealedProcess, SessionProcess
from lexarena.storage.mongo import Namespace
from tests import builders
from tests.conftest import ENV_FILE, SEALED_ENV_FILE
from tests.test_judges_bench import CFG, judge

pytestmark = pytest.mark.integration

CASE = "TESTCASE_EVAL_0001"
REPORT = ThemisGlobalReport(consistency={}, rebuttal_depth={}, contradictions=[])


@pytest.fixture(scope="module")
def procs() -> Iterator[tuple[SessionProcess, SealedProcess]]:
    ns = Namespace(prefix=f"t{uuid.uuid4().hex[:8]}_")
    session = SessionProcess(SecretStore(env_file=[ENV_FILE], environ={}), ns)
    sealed = SealedProcess(SecretStore(env_file=[ENV_FILE, SEALED_ENV_FILE], environ={}), ns)
    clerk = sealed.clerk()
    clerk.cases.put(builders.case(CASE))
    clerk.ground_truth.put(builders.ground_truth(CASE, "<sentinel>"))  # I1 favours PETITIONER; overall PETITIONER
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


def test_evaluation_only_after_the_bench_verdict(procs: tuple[SessionProcess, SealedProcess]) -> None:
    session, sealed = procs
    sid = _started(session)
    with pytest.raises(NotEvaluableError):
        evaluate_session(sealed.evaluator(), sid)  # IN_PROGRESS: no bench yet
    decisions = [judge(p, "PETITIONER", {"I1": "PETITIONER"}) for p in ("TEXTUALIST", "PURPOSIVIST", "PROCEDURALIST")]
    verdict = decide_bench(decisions, ["I1"], CFG)
    session.orchestrator().sessions.record_bench_verdict(sid, decisions=decisions, bench=verdict, themis_global=REPORT)
    result = evaluate_session(sealed.evaluator(), sid)
    assert result.session.state == SessionState.EVALUATED
    ev = result.session.evaluation
    assert ev is not None and (ev.winner_matches_real, ev.issue_alignment, ev.real_overall) == (True, 1.0, "PETITIONER")
    assert result.outcome.bench_winner == "PETITIONER" and result.outcome.split == "DEV"
    with pytest.raises(Exception, match="EVALUATED"):
        evaluate_session(sealed.evaluator(), sid)  # never twice: the transition is compare-and-set


def test_a_session_from_before_the_bench_is_refused(procs: tuple[SessionProcess, SealedProcess]) -> None:
    session, sealed = procs
    sid = _started(session)
    session.orchestrator().sessions.record_verdict(
        sid, scorecards=[], aggregate=Aggregate(PETITIONER=0.5, RESPONDENT=0.5), winner="TIE", themis_global=REPORT
    )
    with pytest.raises(NotEvaluableError, match="no bench verdict"):
        evaluate_session(sealed.evaluator(), sid)


def test_ground_truth_stays_sealed_for_an_unfinished_session(procs: tuple[SessionProcess, SealedProcess]) -> None:
    _, sealed = procs
    session, _ = procs
    sid = _started(session)
    with pytest.raises(SealedError):
        sealed.evaluator().ground_truth.get(CASE, session_id=sid)
