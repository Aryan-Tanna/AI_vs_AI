"""Job handlers. Every model call is wrapped in `ctx.step(...)` so it is checkpointed and never repeated
after a usage-limit interruption."""
import hashlib
import json

from claude_agent_sdk import tool

from lexarena.agents import prompts
from lexarena.agents.framework import framework_for, side_description
from lexarena.llm.agent import AgentSpec
from lexarena.public_db import UnspoiledStore, retrieval_exclusions, to_json
from lexarena.schemas.runtime import BaselinePrediction, SmokeOutput, Turn
from lexarena.sources.registry import get_registry
from lexarena.session.runner import JobContext
from lexarena.themis.checkers import build_checkers
from lexarena.themis.local import verify_turn
from lexarena.tools.record import make_record_tools
from lexarena.tools.research import make_research_tools
from lexarena.tools.registry import select_tools


async def smoke(ctx: JobContext) -> dict:
    """One tiny agent call: proves subscription auth, tool calling and isolation work."""
    @tool("get_case_fact", "Return a test fact.", {})
    async def get_case_fact(_args):
        return {"content": [{"type": "text", "text": "Default date on record: 31.03.2016"}]}

    spec = AgentSpec(role="smoke", system_prompt=prompts.SMOKE,
                     tools=select_tools("smoke", {"get_case_fact": get_case_fact}),
                     output_model=SmokeOutput, cache_salt=ctx.job.key)
    res = await ctx.step("smoke", lambda: _run(ctx, spec, "Run the check."))
    called = any(t["type"] == "tool_use" and t["name"].endswith("get_case_fact") for t in res["trace"])
    return {"output": res["output"], "tool_called": called, "model": res["model"], "usage": res["usage"]}


async def baseline(ctx: JobContext) -> dict:
    """Single-LLM baseline (CLAUDE.md §9.2): one model reads the unspoiled case and predicts the outcome."""
    case = UnspoiledStore(ctx.settings.public_db_dir).get(ctx.job.payload["case_uid"])
    law_as_of = case.law_as_of
    spec = AgentSpec(role="baseline",
                     system_prompt=prompts.BASELINE.format(disclaimer=prompts.DISCLAIMER, law_as_of=law_as_of),
                     output_model=BaselinePrediction, cache_salt=_case_salt(case))
    res = await ctx.step("predict", lambda: _run(ctx, spec, "Appeal record:\n" + to_json(case.sections())))
    return {"case_uid": case.case_uid, "prediction": res["output"], "model": res["model"]}


async def debate(ctx: JobContext) -> dict:
    """Appellant vs respondent over the MVP schedule. Per turn: the advocate drafts (record + research tools),
    then THEMIS-LOCAL runs (extract -> Stage A up to 3 attempts -> Stage B once) and the final version is
    published with its flags. Payload `themis: false` skips the gate (turns marked NOT_RUN).

    Not wired yet: bench questions, THEMIS-GLOBAL, the bench.
    """
    settings = ctx.settings
    case = UnspoiledStore(settings.public_db_dir).get(ctx.job.payload["case_uid"])
    law_as_of = case.law_as_of
    run_id = ctx.job.payload.get("run_id", "dev")
    use_themis = ctx.job.payload.get("themis", True)
    services = get_registry(settings)
    web_tools, web_rules = services.web_permissions()
    external_mcp = {m['name']: {k: v for k, v in m.items() if k in ('type', 'command', 'args', 'env', 'url')}
                    for m in services.mcp_servers}
    exclude = retrieval_exclusions(settings.public_db_dir, case.case_uid)
    schedule = prompts.MVP_SCHEDULE
    transcript: list[dict] = list(ctx.job.checkpoint.get("transcript", []))
    available = {**make_record_tools(case, transcript), **make_research_tools(law_as_of, services, exclude)}
    tools = select_tools("advocate", available)

    for i, (side, stage) in enumerate(schedule, start=1):
        if any(t["turn"] == i for t in transcript):
            continue
        salt = f"{_case_salt(case)}|{side}|{_transcript_hash(transcript)}"
        spec = AgentSpec(
            role="advocate",
            system_prompt=prompts.ADVOCATE.format(
                side=side_description(side, case.appellant_role, case.respondent_roles), disclaimer=prompts.DISCLAIMER,
                framework=framework_for(case.proceeding_type, case.appeal_scope.restricted_grounds), law_as_of=law_as_of,
                sources=services.describe()),
            tools=tools, output_model=Turn, cache_salt=salt,
            builtin_tools=web_tools, allow_rules=web_rules, external_mcp=external_mcp)
        prompt = prompts.ADVOCATE_TURN.format(case_uid=case.case_uid, stage=stage, turn=i, total=len(schedule),
                                              stage_instruction=prompts.STAGE_INSTRUCTIONS[stage])
        draft = await ctx.step(f"turn_{i:02d}/draft", lambda: _run(ctx, spec, prompt))

        themis: dict = {"status": "NOT_RUN"}
        final, flags, notes = draft["output"], [], []
        if use_themis:
            checks = build_checkers(case, services, ctx.backend, turn=i, stage=stage, advocate_spec=spec,
                                    salt=salt, notes_sink=notes, declared_n=len(draft["output"].get("claims", [])))
            gate = await verify_turn(draft["output"], checks, step=ctx.step, prefix=f"turn_{i:02d}/themis")
            final, flags = gate.turn, [f.to_dict() for f in gate.flags]
            themis = {"status": gate.status, "stage_a_attempts": gate.stage_a_attempts, "notes": notes, "log": gate.log}

        prev = transcript[-1]["hash"] if transcript else ""
        entry = {"turn": i, "speaker": side, "stage": stage, **final, "themis": themis, "flags": flags,
                 "tool_trace": draft["trace"], "model": draft["model"]}
        entry["hash"] = hashlib.sha256((prev + json.dumps(entry, sort_keys=True, ensure_ascii=False, default=str)).encode()).hexdigest()
        transcript.append(entry)
        ctx.job.checkpoint["transcript"] = transcript
        ctx.queue.save_checkpoint(ctx.job.id, ctx.job.checkpoint)

    out_dir = settings.runs_dir / run_id / case.case_uid
    out_dir.mkdir(parents=True, exist_ok=True)
    sealed = {"case_uid": case.case_uid, "law_as_of": law_as_of.isoformat(), "turns": transcript,
              "seal": transcript[-1]["hash"], "disclaimer": prompts.DISCLAIMER}
    (out_dir / "transcript.json").write_text(json.dumps(sealed, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    statuses = [t["themis"]["status"] for t in transcript]
    return {"case_uid": case.case_uid, "stage": "transcript_sealed", "seal": sealed["seal"],
            "themis": {s: statuses.count(s) for s in set(statuses)}, "path": str(out_dir / "transcript.json")}


async def _run(ctx: JobContext, spec: AgentSpec, prompt: str) -> dict:
    res = await ctx.backend.run(spec, prompt)
    return {"output": res.output, "text": res.text, "trace": res.trace, "model": res.model,
            "usage": res.usage, "num_turns": res.num_turns, "cached": res.cached}


def _case_salt(case) -> str:
    return case.case_uid + ":" + hashlib.sha256(case.model_dump_json().encode()).hexdigest()[:16]


def _transcript_hash(transcript: list[dict]) -> str:
    return transcript[-1]["hash"] if transcript else "empty"


HANDLERS = {"smoke": smoke, "baseline": baseline, "debate": debate}
