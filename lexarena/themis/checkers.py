"""Builds the THEMIS-LOCAL Checkers for one case and one turn: Haiku extraction, Stage A (code), Stage B
(Haiku), and revision by the same advocate (CLAUDE.md §8.3)."""
import datetime as dt
import json

from lexarena.agents import prompts
from lexarena.llm.agent import AgentError, AgentSpec, Backend
from lexarena.public_db import UnspoiledCase
from lexarena.schemas.runtime import Turn
from lexarena.sources.registry import SourceRegistry
from lexarena.themis.claims import ClaimSet, StageBOutput
from lexarena.themis.local import Checkers, Finding
from lexarena.themis.stage_a import StageA


def _record_extract(case: UnspoiledCase) -> str:
    s = case.sections()
    keep = {k: s[k] for k in ("impugned_order", "chronology", "typed_facts", "record_documents", "record_conflicts") if k in s}
    return json.dumps(keep, ensure_ascii=False, default=str)


def build_checkers(case: UnspoiledCase, services: SourceRegistry, backend: Backend, *, turn: int, stage: str,
                   advocate_spec: AgentSpec, salt: str, notes_sink: list, declared_n: int = 0) -> Checkers:
    stage_a = StageA(case, services.law, services.authorities, services.mode)
    cutoff = case.law_as_of + dt.timedelta(days=1)
    facts = {k: (f.values if f.conflict else f.value) for k, f in case.typed_facts.all_facts().items()}
    events = [f"{e.id}: {e.date or 'undated'} - {e.event}" for e in case.chronology]
    closed_after = case.appeal_scope.record_closed_after_turn
    declared = {"n": declared_n}       # set from the draft so the note also works when extraction is resumed from a checkpoint
    failures: list[dict] = []       # extraction / Stage B failures: noted on the turn instead of failing the job

    async def extract(t: dict) -> dict:
        declared["n"] = len(t.get("claims", []))
        spec = AgentSpec(role="extractor", system_prompt=prompts.EXTRACTOR, output_model=ClaimSet, cache_salt=salt)
        msg = prompts.EXTRACTOR_INPUT.format(facts=json.dumps(facts, default=str), events="; ".join(events),
                                             declared=json.dumps(t.get("claims", []), ensure_ascii=False), prose=t["prose"])
        try:
            return (await backend.run(spec, msg)).output
        except AgentError as e:
            return {"claims": [], "_extraction_error": str(e)[:300]}

    def run_stage_a(claims: dict) -> list[Finding]:
        error = claims.pop("_extraction_error", None) if isinstance(claims, dict) else None
        res = stage_a.run(claims)
        notes_sink[:] = res.notes                      # notes from the latest Stage A run go on the transcript
        notes_sink[:0] = failures
        if error:
            notes_sink.insert(0, {"note": f"EXTRACTION_FAILED: {error}; Stage A checked nothing for this attempt"})
        elif not claims.get("claims") and declared["n"]:
            notes_sink.insert(0, {"note": f"EXTRACTION_EMPTY: the advocate declared {declared['n']} claims but none were "
                                          "extracted; Stage A checked nothing for this turn"})
        return res.findings

    async def stage_b(t: dict, claims: dict) -> list[Finding]:
        cs = ClaimSet.model_validate(claims)
        props = {}
        for c in cs.claims:
            if c.authority_title:
                st = services.authorities.status(c.authority_title, cutoff, c.authority_court)
                props[c.authority_title] = st.proposition if st.found else "(not found)"
        rule = (f"facts introduced after the record closed (this is turn {turn}; the record closed after turn {closed_after})"
                if turn > closed_after else "not applicable at this stage; report none")
        spec = AgentSpec(role="verifier", system_prompt=prompts.VERIFIER.format(new_fact_rule=rule),
                         output_model=StageBOutput, cache_salt=salt)
        msg = prompts.VERIFIER_INPUT.format(record=_record_extract(case), authorities=json.dumps(props, ensure_ascii=False),
                                            claims=cs.model_dump_json(exclude_none=True), prose=t["prose"])
        try:
            out = StageBOutput.model_validate((await backend.run(spec, msg)).output)
        except AgentError as e:
            failures.append({"note": f"STAGE_B_FAILED: {str(e)[:300]}"})
            notes_sink.append(failures[-1])
            return []
        by_id = {c.id: c.text for c in cs.claims}
        return [Finding(f.code, by_id.get(f.claim_id, f.claim_id), f.evidence, "B") for f in out.findings]

    async def revise(t: dict, findings: list[Finding], n: int) -> dict:
        listed = "\n".join(f"- {f.code}: \"{f.claim}\" ({f.evidence})" for f in findings)
        msg = prompts.REVISE.format(case_uid=case.case_uid, turn=turn, stage=stage, findings=listed,
                                    previous=json.dumps(t, ensure_ascii=False))
        spec = AgentSpec(role="advocate", system_prompt=advocate_spec.system_prompt, tools=advocate_spec.tools,
                         output_model=Turn, cache_salt=f"{advocate_spec.cache_salt}|revise{n}",
                         builtin_tools=advocate_spec.builtin_tools, allow_rules=advocate_spec.allow_rules,
                         external_mcp=advocate_spec.external_mcp)
        return (await backend.run(spec, msg)).output

    return Checkers(extract=extract, stage_a=run_stage_a, stage_b=stage_b, revise=revise)
