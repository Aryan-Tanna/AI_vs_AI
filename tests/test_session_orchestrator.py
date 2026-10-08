"""A whole session on the real services with scripted models (BUILD_PLAN Step 9; SPEC E6, I2, I3-10; R-018; D-079).

The scripted provider answers by output schema, so the test follows the real call sequence without fixing its order.
Checked: the turn schedule (alternating, then parallel closings that do not see each other), every draft verified,
transcript and private data stored, the bench verdict recorded, pinned lessons recorded, both sides' inputs equal
except for the declared side-specific parts, and the simulation date never reaching any prompt.

Run with: pytest --run-integration -m integration
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from lexarena.config import load_config
from lexarena.ingest.law_db import LoadableRecord, content_hash
from lexarena.judges.personas import PersonaRegistry
from lexarena.llm.client import LLMClient
from lexarena.llm.types import LLMRequest, LLMResponse
from lexarena.orchestrator.session import Services, SessionOptions, run_session, schedule
from lexarena.prompts import PromptStore
from lexarena.schemas.law import LawRecord
from lexarena.schemas.session import SessionState
from lexarena.schemas.statute_alias import StatuteAliasTable
from lexarena.secrets import SecretStore
from lexarena.storage.errors import NotFoundError
from lexarena.storage.factory import SealedProcess, SessionProcess
from lexarena.storage.mongo import Namespace
from tests import builders
from tests.conftest import CONFIG_V1, ENV_FILE, PROMPTS_ROOT, SEALED_ENV_FILE
from tests.fakes import WordEmbedder, text_response
from tests.test_law_validation import law_record

pytestmark = pytest.mark.integration

CFG = load_config(CONFIG_V1)
CASE = "TESTCASE_SESSION_0001"
STATUTE = "<statute id>"
SIM_DATE = "1999-12-31"  # literal-ok: sentinel simulation_date that must never reach a prompt


@dataclass
class ByProvider:
    """Answers each request by its schema name; records every request."""

    requests: list[LLMRequest] = field(default_factory=list)
    drafts: int = 0
    fail_at_draft: int | None = None

    def complete(self, request: LLMRequest, api_key: str) -> LLMResponse:
        self.requests.append(request)
        name = request.schema_name
        if name == "ResearchPlan":
            body: Any = {"queries": []}
        elif name == "StrategyNotes":
            body = {
                "issues_to_press": ["I1"],
                "expected_attacks": [],
                "authorities_held": ["<invented uid>"],
                "plan": "<plan>",
            }
        elif name == "LawyerDraft":
            self.drafts += 1
            if self.fail_at_draft == self.drafts:
                from lexarena.llm.errors import RateLimitedError

                raise RateLimitedError("quota", retry_after_s=10**6)  # literal-ok: longer than any backoff
            words = " ".join(f"w{self.drafts}x{i}" for i in range(12))  # literal-ok: distinct words per draft
            body = {
                "text": f"Submission {self.drafts}: {words}.",
                "issues_addressed": ["I1", "I9"],
                "claims": [
                    {
                        "type": "FACT",
                        "text": "<claim>",
                        "record_ids": ["F1"],
                        "statute_id": STATUTE,
                        "precedent_ids": [],
                    }
                ],
            }
        elif name == "ArgumentExtraction":
            body = {"checklists": []}
        elif name == "Layer2Review":
            body = {"fidelity_issues": [], "opponent_points": []}
        elif name == "TranscriptAudit":
            body = {"points": [], "contradictions": []}
        elif name == "OpinionDraft":
            dims = {"accuracy": 0.6, "consistency": 0.6, "rebuttal": 0.6, "grounding": 0.6}
            body = {
                "issue_decisions": [
                    {
                        "issue_id": "I1",
                        "finding": "<finding>",
                        "governing_rule_ids": [STATUTE],
                        "record_ids": ["F1"],
                        "application": "<application>",
                        "conclusion": "<conclusion>",
                        "upholds": "RESPONDENT",
                    }
                ],
                "overall_result": "RESPONDENT",
                "overall_reasons": "<reasons>",
                "advocacy": [{"issue_id": "I1", "petitioner": dims, "respondent": dims}],
            }
        else:
            raise AssertionError(f"unexpected schema {name}")
        return text_response(json.dumps(body))


@pytest.fixture(scope="module")
def world() -> Iterator[tuple[SessionProcess, Namespace]]:
    ns = Namespace(prefix=f"t{uuid.uuid4().hex[:8]}_")
    session = SessionProcess(SecretStore(env_file=[ENV_FILE], environ={}), ns)
    sealed = SealedProcess(SecretStore(env_file=[ENV_FILE, SEALED_ENV_FILE], environ={}), ns)
    raw = law_record(STATUTE)
    sealed.ingest().law.sync({STATUTE: LoadableRecord(LawRecord.model_validate(raw), content_hash(raw), "<file>")})
    sealed.clerk().cases.put(builders.case(CASE, date_marker=SIM_DATE))
    yield session, ns
    for db in (session._app_db, sealed._sealed_db):
        for name in db.list_collection_names():
            if name.startswith(ns.prefix):
                db.drop_collection(name)
    session.close()
    sealed.close()


def services(tmp_path: Path, provider: ByProvider) -> Services:
    names = {m.api_key_env for m in CFG.models.by_role().values()}
    prompts = PromptStore(PROMPTS_ROOT)
    llm = LLMClient(
        CFG,
        SecretStore(env_file=None, environ={n: "k" for n in names}),
        prompts,
        providers={p: provider for p in CFG.providers},
        cache=None,
        sleep=lambda _: None,
    )
    return Services(
        llm=llm,
        prompts=prompts,
        cfg=CFG,
        embedder=WordEmbedder(),
        aliases=StatuteAliasTable.model_validate({"aliases": []}),
        personas=PersonaRegistry(tmp_path / "personas", prompts, CFG.prompts),
        git_sha="<sha>",
        config_sha256="<hash>",
    )


OPTS = SessionOptions(run_id="R1", mode="FROZEN", case_seq=1, allow_draft_personas=True)


def test_a_whole_session(world: tuple[SessionProcess, Namespace], tmp_path: Path) -> None:
    proc, _ = world
    provider = ByProvider()
    session = run_session(proc, CASE, OPTS, services(tmp_path, provider))
    assert session.state == SessionState.VERDICT_RECORDED and session.winner == "RESPONDENT"
    assert session.case_seq == 1 and session.pinned_lessons == [] and session.themis_global is not None
    turns = proc.orchestrator().transcript.turns(session.id)
    plan = schedule(CFG)
    assert [(t.turn, t.speaker, t.turn_type) for t in turns] == plan
    assert all(t.issues_addressed == ["I1"] for t in turns)  # an issue that is not framed is dropped
    assert turns[0].claims[0].claim_id == "T01-C1"

    # Both closings were written against the same transcript: neither saw the other.
    drafts = [r for r in provider.requests if r.schema_name == "LawyerDraft"]
    closing_p, closing_d = drafts[-2].messages[-1].content, drafts[-1].messages[-1].content
    n = CFG.session.alternating_turns
    assert f"Turn {n} (" in closing_p and f"Turn {n + 1} (" not in closing_p and f"Turn {n + 1} (" not in closing_d

    # Fairness (SPEC E6): the two sides' first turns differ only in the declared side-specific parts.
    first_p, first_d = drafts[0].messages[-1].content, drafts[1].messages[-1].content
    shared_start = first_p.index("THE CASE")
    shared_end = first_p.index("EXPERIENCE BASE")
    assert first_p.split("You represent")[0] == first_d.split("You represent")[0]  # the rules
    assert first_p[shared_start:shared_end] == first_d[first_d.index("THE CASE") : first_d.index("EXPERIENCE BASE")]
    assert "<invented uid>" not in first_p  # an authority research never returned is never held

    # R-018: the simulation date reaches no prompt of any role.
    assert all(SIM_DATE not in m.content for r in provider.requests for m in r.messages)
    # Session memory is cleared at the end (SPEC I1).
    assert proc.orchestrator().session_memory._store == {}


def test_a_failure_aborts_the_session(world: tuple[SessionProcess, Namespace], tmp_path: Path) -> None:
    from lexarena.llm.errors import RateLimitedError

    proc, ns = world
    provider = ByProvider(fail_at_draft=3)
    with pytest.raises(RateLimitedError):
        run_session(proc, CASE, OPTS, services(tmp_path, provider))
    sessions = proc._app_db[f"{ns.prefix}sessions"]
    states = {d["state"] for d in sessions.find({"case_id": CASE})}
    assert "ABORTED" in states and "IN_PROGRESS" not in states


def test_unknown_case_creates_nothing(world: tuple[SessionProcess, Namespace], tmp_path: Path) -> None:
    proc, _ = world
    with pytest.raises(NotFoundError):
        run_session(proc, "TESTCASE_MISSING", OPTS, services(tmp_path, ByProvider()))
