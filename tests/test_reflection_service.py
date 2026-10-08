"""Reflection end to end on the real services (BUILD_PLAN Step 12; SPEC F; D-077): an evaluated session's lessons are
filtered, stored in the experience memory and the session moves to REFLECTED; a session process can read the memory
but Qdrant refuses its writes.

Run with: pytest --run-integration -m integration
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterator
from typing import Any

import pytest

from lexarena.evaluator.evaluate import evaluate_session
from lexarena.judges.bench import decide_bench
from lexarena.llm.client import LLMClient
from lexarena.prompts import PromptStore
from lexarena.reflection.reflect import NotReflectableError, Reflection
from lexarena.schemas.session import SessionState, ThemisGlobalReport
from lexarena.secrets import SecretStore
from lexarena.storage.factory import SealedProcess, SessionProcess
from lexarena.storage.lessons import LessonRepository
from lexarena.storage.mongo import Namespace
from lexarena.storage.policy import Principal, Role
from tests import builders
from tests.conftest import ENV_FILE, PROMPTS_ROOT, SEALED_ENV_FILE
from tests.fakes import FakeProvider, WordEmbedder, text_response
from tests.judge_fixtures import CFG
from tests.test_judges_bench import CFG as JUDGING
from tests.test_judges_bench import judge

pytestmark = pytest.mark.integration

CASE = "TESTCASE_REFLECT_0001"
REPORT = ThemisGlobalReport(
    consistency={}, rebuttal_depth={"PETITIONER": {"depth": 1.0}, "RESPONDENT": {"depth": 0.5}}, contradictions=[]
)


@pytest.fixture(scope="module")
def procs() -> Iterator[tuple[SessionProcess, SealedProcess, Namespace]]:
    ns = Namespace(prefix=f"t{uuid.uuid4().hex[:8]}_")
    session = SessionProcess(SecretStore(env_file=[ENV_FILE], environ={}), ns)
    sealed = SealedProcess(SecretStore(env_file=[ENV_FILE, SEALED_ENV_FILE], environ={}), ns)
    sealed.clerk().cases.put(builders.case(CASE))
    sealed.clerk().ground_truth.put(builders.ground_truth(CASE, "<sentinel>"))  # I1, LAW, source para "1"
    yield session, sealed, ns
    for db in (session._app_db, sealed._sealed_db):
        for name in db.list_collection_names():
            if name.startswith(ns.prefix):
                db.drop_collection(name)
    for c in sealed._qdrant.get_collections().collections:
        if c.name.startswith(ns.prefix):
            sealed._qdrant.delete_collection(c.name)
    session.close()
    sealed.close()


def evaluated_session(session: SessionProcess, sealed: SealedProcess) -> str:
    sid = f"S_{uuid.uuid4().hex[:8]}"
    orch = session.orchestrator()
    orch.sessions.create(builders.session(sid, CASE).model_copy(update={"case_seq": 2}))
    orch.sessions.start(sid)
    for n, side in ((1, "PETITIONER"), (2, "RESPONDENT")):
        orch.transcript.publish(builders.published_turn(sid, CASE, n, side))  # type: ignore[arg-type]
        session.themis_local(side, sid, builders.SCOPE).private_turns.put(  # type: ignore[arg-type]
            builders.private_turn(sid, CASE, n, side, "<private>")  # type: ignore[arg-type]
        )
    decisions = [judge(p, "PETITIONER", {"I1": "PETITIONER"}) for p in ("TEXTUALIST", "PURPOSIVIST", "PROCEDURALIST")]
    orch.sessions.record_bench_verdict(
        sid, decisions=decisions, bench=decide_bench(decisions, ["I1"], JUDGING), themis_global=REPORT
    )
    evaluate_session(sealed.evaluator(), sid)
    return sid


def candidate(**change: Any) -> dict[str, Any]:
    base = {
        "lesson_type": "ADVOCACY",
        "for_whom": "PETITIONER",
        "statute_ids": ["<statute id>"],
        "error_code": None,
        "trigger": "the debtor disputes the date of default",
        "lesson": "Tie the date of default to the record item that states it before arguing limitation.",
        "issue_ids": ["I1"],
        "source_paras": ["1"],
        "severity": 3,
    }
    return {**base, **change}


def reflection(answer: dict[str, Any]) -> tuple[Reflection, FakeProvider]:
    names = {m.api_key_env for m in CFG.models.by_role().values()}
    provider = FakeProvider([text_response(json.dumps(answer))])
    llm = LLMClient(
        CFG,
        SecretStore(env_file=None, environ={n: "k" for n in names}),
        PromptStore(PROMPTS_ROOT),
        providers={CFG.models.reflection.provider: provider},
        cache=None,
        sleep=lambda _: None,
    )
    return Reflection(llm, PromptStore(PROMPTS_ROOT), CFG, WordEmbedder()), provider


def test_lessons_are_filtered_stored_and_the_session_reflected(
    procs: tuple[SessionProcess, SealedProcess, Namespace],
) -> None:
    session, sealed, ns = procs
    sid = evaluated_session(session, sealed)
    before = session.orchestrator().lawyer_memory.snapshot()
    engine, provider = reflection(
        {
            "lessons": [
                candidate(),
                candidate(lesson="Against <pseudonym B>, insist on the record."),  # names a pseudonym: rejected
                candidate(lesson_type="LEGAL_RULE", for_whom="BENCH", lesson="A rule of law, stated generally."),
            ]
        }
    )
    stores = sealed.reflection()
    private = {side: sealed.reflection(side).private_turns for side in ("PETITIONER", "RESPONDENT")}
    result = engine.reflect(stores, private, sid, run_id="R1")  # type: ignore[arg-type]
    assert result.session.state == SessionState.REFLECTED
    assert len(result.written) == 2 and any("names a party" in r for r in result.rejected)
    sent = provider.requests[0].messages[-1].content
    assert "<sentinel>" in sent  # reflection reads the real findings, after the verdict
    lawyer = session.orchestrator().lawyer_memory.all()  # the session side reads with the read-only key
    assert [x.party_status for x in lawyer] == ["FINANCIAL_CREDITOR"]
    assert session.orchestrator().judge_memory.all()[0].lesson_type == "LEGAL_RULE"
    assert session.orchestrator().lawyer_memory.snapshot() != before
    # Even a role allowed to write cannot, through the session process's read-only Qdrant key (D-034).
    writer = LessonRepository(Principal(Role.REFLECTION), session._qdrant, "LAWYER", ns.prefix)
    with pytest.raises(Exception, match=r"403|[Ff]orbidden|[Pp]ermission"):
        writer.upsert(lawyer[0], [0.0] * WordEmbedder.dim)
    with pytest.raises(NotReflectableError):
        engine.reflect(stores, private, sid, run_id="R1")  # type: ignore[arg-type]
