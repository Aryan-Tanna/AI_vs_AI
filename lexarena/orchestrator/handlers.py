"""Job handlers. Every model call is wrapped in `ctx.step(...)` so it is checkpointed and never repeated
after a usage-limit interruption."""
import hashlib
import json

from claude_agent_sdk import tool

from lexarena.agents import prompts
from lexarena.llm.agent import AgentSpec
from lexarena.public_db import UnspoiledStore, to_json
from lexarena.schemas.runtime import BaselinePrediction, SmokeOutput, Turn
from lexarena.session.runner import JobContext
from lexarena.tools.record import make_record_tools
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
    law_as_of = case.sections().get("law_as_of", "the date of decision")
    spec = AgentSpec(role="baseline",
                     system_prompt=prompts.BASELINE.format(disclaimer=prompts.DISCLAIMER, law_as_of=law_as_of),
                     output_model=BaselinePrediction, cache_salt=_case_salt(case))
    res = await ctx.step("predict", lambda: _run(ctx, spec, "Appeal record:\n" + to_json(case.sections())))
    return {"case_uid": case.case_uid, "prediction": res["output"], "model": res["model"]}


async def debate(ctx: JobContext) -> dict:
    """Appellant vs respondent over the MVP schedule; one checkpointed step per turn.

    Not wired yet: THEMIS-LOCAL (turns are published with status NOT_RUN), bench, global audit.
    """
    case = UnspoiledStore(ctx.settings.public_db_dir).get(ctx.job.payload["case_uid"])
    law_as_of = case.sections().get("law_as_of", "the date of decision")
    run_id = ctx.job.payload.get("run_id", "dev")
    schedule = prompts.MVP_SCHEDULE
    transcript: list[dict] = list(ctx.job.checkpoint.get("transcript", []))
    record_tools = make_record_tools(case, transcript)       # read_transcript sees the list as it grows

    for i, (side, stage) in enumerate(schedule, start=1):
        if any(t["turn"] == i for t in transcript):
            continue
        spec = AgentSpec(
            role="advocate",
            system_prompt=prompts.ADVOCATE.format(side=side.lower(), disclaimer=prompts.DISCLAIMER, law_as_of=law_as_of),
            tools=select_tools("advocate", record_tools),
            output_model=Turn,
            cache_salt=f"{_case_salt(case)}|{side}|{_transcript_hash(transcript)}",
        )
        prompt = prompts.ADVOCATE_TURN.format(case_uid=case.case_uid, stage=stage, turn=i, total=len(schedule),
                                              stage_instruction=prompts.STAGE_INSTRUCTIONS[stage])
        res = await ctx.step(f"turn_{i:02d}", lambda: _run(ctx, spec, prompt))
        prev = transcript[-1]["hash"] if transcript else ""
        entry = {"turn": i, "speaker": side, "stage": stage, **res["output"],
                 "themis": {"status": "NOT_RUN"}, "flags": [], "tool_trace": res["trace"], "model": res["model"]}
        entry["hash"] = hashlib.sha256((prev + json.dumps(entry, sort_keys=True, ensure_ascii=False)).encode()).hexdigest()
        transcript.append(entry)
        ctx.job.checkpoint["transcript"] = transcript
        ctx.queue.save_checkpoint(ctx.job.id, ctx.job.checkpoint)

    out_dir = ctx.settings.runs_dir / run_id / case.case_uid
    out_dir.mkdir(parents=True, exist_ok=True)
    sealed = {"case_uid": case.case_uid, "law_as_of": law_as_of, "turns": transcript,
              "seal": transcript[-1]["hash"], "disclaimer": prompts.DISCLAIMER}
    (out_dir / "transcript.json").write_text(json.dumps(sealed, ensure_ascii=False, indent=1), encoding="utf-8")
    return {"case_uid": case.case_uid, "stage": "transcript_sealed", "seal": sealed["seal"],
            "path": str(out_dir / "transcript.json")}


async def _run(ctx: JobContext, spec: AgentSpec, prompt: str) -> dict:
    res = await ctx.backend.run(spec, prompt)
    return {"output": res.output, "text": res.text, "trace": res.trace, "model": res.model,
            "usage": res.usage, "num_turns": res.num_turns, "cached": res.cached}


def _case_salt(case) -> str:
    return case.case_uid + ":" + hashlib.sha256(case.model_dump_json().encode()).hexdigest()[:16]


def _transcript_hash(transcript: list[dict]) -> str:
    return transcript[-1]["hash"] if transcript else "empty"


HANDLERS = {"smoke": smoke, "baseline": baseline, "debate": debate}
