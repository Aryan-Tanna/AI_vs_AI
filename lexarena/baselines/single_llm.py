"""The single-LLM baseline (BUILD_PLAN Step 12; INTENT hypothesis H1; SPEC G1; D-049, D-072).

One model call decides the same case file the bench sees (the agent view, the statutes as of the case dates), with no
debate, no verifier and no revision. Its model role is `evaluation.single_llm_role` in config; using the judges' role
makes the comparison isolate what the debate and verification add.

It runs on the session side and reads nothing sealed. A framed issue the model leaves out, repeats or renames is simply
not predicted, and is recorded as a problem; the baseline is never repaired into agreement with the bench.
"""

from __future__ import annotations

from collections import Counter

from lexarena.judges.packet import render_case, render_issues, render_statutes
from lexarena.llm.client import LLMClient
from lexarena.prompts import PromptStore
from lexarena.schemas.bench import Upholds
from lexarena.schemas.case import AgentCaseView
from lexarena.schemas.config import AppConfig
from lexarena.schemas.evaluation import BaselinePrediction, SingleLLMDraft
from lexarena.storage.temporal import StatuteView


def predict(
    llm: LLMClient,
    prompts: PromptStore,
    cfg: AppConfig,
    case: AgentCaseView,
    views: dict[str, StatuteView],
    *,
    session_id: str,
) -> BaselinePrediction:
    ref = cfg.prompts.single_llm
    framed = [i.issue_id for i in case.framed_issues]
    prompt = prompts.render(
        ref.id,
        ref.version,
        case=render_case(case),
        issues=render_issues(case),
        issue_ids=", ".join(framed),
        statutes=render_statutes(views),
    )
    role = cfg.evaluation.single_llm_role
    draft = llm.complete_json(role=role, user=prompt, schema=SingleLLMDraft, session_id=session_id).value
    counts = Counter(d.issue_id for d in draft.issue_decisions)
    problems = [f"MISSING_ISSUE {i}" for i in framed if i not in counts]
    problems += [f"UNKNOWN_ISSUE {i}" for i in sorted(counts) if i not in framed]
    problems += [f"DUPLICATE_ISSUE {i}" for i, n in sorted(counts.items()) if n > 1 and i in framed]
    issues: dict[str, Upholds] = {
        d.issue_id: d.upholds for d in draft.issue_decisions if d.issue_id in framed and counts[d.issue_id] == 1
    }
    return BaselinePrediction(
        case_id=case.case_id,
        kind="SINGLE_LLM",
        model=cfg.models.by_role()[role].name,
        prompt_id=prompt.prompt_id,
        prompt_sha256=prompt.sha256,
        overall=draft.overall_result,
        issues=issues,
        problems=problems,
    )
