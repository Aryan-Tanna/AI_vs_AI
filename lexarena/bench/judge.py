"""Judge agents. Each judge is an agent with read-only tools; its record references and authorities are then
checked deterministically (THEMIS Stage A rules) and it gets one chance to correct flagged items."""
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from lexarena.agents import prompts
from lexarena.agents.framework import framework_for
from lexarena.bench.personas import PERSONAS
from lexarena.llm.agent import AgentSpec, Backend
from lexarena.public_db import UnspoiledCase
from lexarena.schemas.runtime import Label
from lexarena.sources.registry import SourceRegistry
from lexarena.themis.claims import ClaimSet
from lexarena.themis.global_ import transcript_text
from lexarena.themis.stage_a import StageA


class _Out(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AuthorityCite(_Out):
    title: str
    court: Literal["SC", "NCLAT", "HC", "NCLT", "OTHER"] | None = None


class IssueDecision(_Out):
    issue: str = Field(pattern=r"^I\d+$")
    finding: str = Field(max_length=200, description="Short answer to the issue, e.g. 'Application within limitation'")
    reasons: str
    record_refs: list[str] = Field(description="Record ids relied on (E#/D#)")
    authorities_relied: list[AuthorityCite]
    disagrees_with_global: str | None = Field(None, description="Which audit finding you reject, and why")


class Judgment(_Out):
    issue_decisions: list[IssueDecision]
    label: Label
    appellant_won: bool
    summary: str = Field(description="Three to six sentences")


class BenchQuestions(_Out):
    questions: list[str] = Field(max_length=2)


def _claims_of(judgment: dict) -> ClaimSet:
    """Turn a judgment's references into claims so the same Stage A rules check judges and advocates alike."""
    claims, n = [], 0
    for d in judgment["issue_decisions"]:
        for ref in d.get("record_refs", []):
            n += 1
            claims.append({"id": f"C{n}", "kind": "RECORD_FACT", "text": f"{d['issue']}: relies on {ref}", "record_ref": ref})
        for a in d.get("authorities_relied", []):
            n += 1
            claims.append({"id": f"C{n}", "kind": "AUTHORITY", "text": f"{d['issue']}: {a['title']}",
                           "authority_title": a["title"], "authority_court": a.get("court")})
    return ClaimSet.model_validate({"claims": claims})


def judge_spec(persona: str, case: UnspoiledCase, tools: list, services: SourceRegistry, salt: str,
               web_tools: list[str], web_rules: list[str]) -> AgentSpec:
    return AgentSpec(
        role="judge",
        system_prompt=prompts.JUDGE.format(disclaimer=prompts.DISCLAIMER, persona_brief=PERSONAS[persona],
                                           framework=framework_for(case.proceeding_type, case.appeal_scope.restricted_grounds),
                                           law_as_of=case.law_as_of),
        tools=tools, output_model=Judgment, cache_salt=f"{salt}|{persona}", builtin_tools=web_tools, allow_rules=web_rules)


def judge_input(case: UnspoiledCase, transcript: list[dict], report: dict) -> str:
    return prompts.JUDGE_INPUT.format(
        case_uid=case.case_uid,
        issues=json.dumps([{"id": i.id, "text": i.text} for i in case.issues], ensure_ascii=False),
        impugned=json.dumps(case.impugned_order.model_dump(mode="json"), ensure_ascii=False),
        transcript=transcript_text(transcript), report=json.dumps(report, ensure_ascii=False, default=str))


async def decide(persona: str, case: UnspoiledCase, transcript: list[dict], report: dict, services: SourceRegistry,
                 backend: Backend, spec: AgentSpec, step) -> dict:
    """One judge: draft judgment -> Stage A check of its references -> at most one revision. Checkpointed."""
    draft = await step(f"bench/{persona}/draft", lambda: _output(backend, spec, judge_input(case, transcript, report)))
    stage_a = StageA(case, services.law, services.authorities, services.mode)
    findings = stage_a.run(_claims_of(draft)).findings
    final, revised = draft, False
    if findings:
        listed = "\n".join(f"- {f.code}: {f.claim} ({f.evidence})" for f in findings)
        msg = prompts.JUDGE_REVISE.format(findings=listed, previous=json.dumps(draft, ensure_ascii=False))
        final = await step(f"bench/{persona}/revise", lambda: _output(backend, spec, msg))
        findings = stage_a.run(_claims_of(final)).findings
        revised = True
    issue_ids = {i.id for i in case.issues}
    missing = sorted(issue_ids - {d["issue"] for d in final["issue_decisions"]})
    return {"persona": persona, "judgment": final, "revised": revised,
            "flags": [f.to_dict() for f in findings], "issues_not_decided": missing}


async def ask_questions(persona: str, case: UnspoiledCase, transcript: list[dict], backend: Backend, salt: str, step) -> list[str]:
    spec = AgentSpec(role="judge", system_prompt=prompts.BENCH_QUESTIONS.format(persona=PERSONAS[persona].split(".")[0],
                                                                              disclaimer=prompts.DISCLAIMER),
                     output_model=BenchQuestions, cache_salt=f"{salt}|{persona}|questions", max_turns=4)
    msg = (f"Issues: {json.dumps([{'id': i.id, 'text': i.text} for i in case.issues], ensure_ascii=False)}\n\n"
           f"Submissions so far:\n{transcript_text(transcript, with_flags=False, max_chars=3000)}")
    out = await step(f"bench/{persona}/questions", lambda: _output(backend, spec, msg))
    return out["questions"]


async def _output(backend: Backend, spec: AgentSpec, msg: str) -> dict:
    return (await backend.run(spec, msg)).output
