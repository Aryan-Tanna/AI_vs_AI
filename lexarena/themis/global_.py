"""THEMIS-GLOBAL: whole-transcript audit, run after the debate and BEFORE the bench (CLAUDE.md §8.3a).

Deterministic part (code): re-run Stage A on every claim in the final transcript, claim drift (the same fact
stated differently in different turns), citations reused after being flagged, flag counts per side.
LLM part (one call): unanswered points and self-contradictions per issue.
Output: findings only, in identical form for both sides. A guard strips any sentence that reads like a verdict
or a recommendation, so the auditor cannot decide the case for the bench.
"""
import json
import re
from collections import defaultdict

from pydantic import BaseModel, ConfigDict, Field

from lexarena.agents import prompts
from lexarena.llm.agent import AgentError, AgentSpec, Backend
from lexarena.public_db import UnspoiledCase
from lexarena.sources.registry import SourceRegistry
from lexarena.themis.claims import ClaimSet
from lexarena.themis.stage_a import StageA

SIDES = ("APPELLANT", "RESPONDENT")
UNSUPPORTED_CODES = {"ERR_UNSUPPORTED_BY_RECORD", "ERR_UNKNOWN_RECORD_REF"}
CITATION_CODES = {"ERR_UNVERIFIED_AUTHORITY", "ERR_ANACHRONISTIC_AUTHORITY", "ERR_MISATTRIBUTED_RATIO"}
VERDICT_WORDS = re.compile(r"\b(stronger|weaker|more persuasive|should (?:be )?(?:allowed|dismissed|succeed|fail)|"
                           r"deserves? to (?:succeed|fail|win|lose)|recommend|wins?|loses?|likely to (?:succeed|fail)|"
                           r"better case|prevail)\b", re.I)


class _Out(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Contradiction(_Out):
    turns: list[int]
    description: str


class SideFindings(_Out):
    unanswered_points: list[str] = Field(description="Points of the OTHER side this side never addressed, with turn numbers")
    contradictions: list[Contradiction]


class IssueAudit(_Out):
    issue: str = Field(pattern=r"^I\d+$")
    appellant: SideFindings
    respondent: SideFindings


class GlobalLLMOutput(_Out):
    issues: list[IssueAudit]


def _strip_verdicts(text: str, notes: list[str]) -> str:
    """Remove sentences that judge the merits (the auditor reports findings only)."""
    kept = []
    for sent in re.split(r"(?<=[.;!?])\s+", text):
        if VERDICT_WORDS.search(sent):
            notes.append(f"removed verdict-like wording: {sent[:120]}")
        else:
            kept.append(sent)
    return " ".join(kept).strip()


def deterministic_audit(case: UnspoiledCase, transcript: list[dict], services: SourceRegistry) -> dict:
    stage_a = StageA(case, services.law, services.authorities, services.mode)
    per_side = {s: {"turns": 0, "claims": 0, "stage_a_findings": [], "flag_counts": defaultdict(int),
                    "unsupported_facts": 0} for s in SIDES}
    seen_values: dict[tuple, list[tuple[int, str, str]]] = defaultdict(list)    # (side, key) -> [(turn, value, text)]
    flagged_titles: dict[str, set[str]] = {s: set() for s in SIDES}
    reused: list[dict] = []

    for t in transcript:
        side = t["speaker"]
        info = per_side[side]
        info["turns"] += 1
        for f in t.get("flags", []):
            info["flag_counts"][f["code"]] += 1
            if f["code"] in UNSUPPORTED_CODES:
                info["unsupported_facts"] += 1
        claims = t.get("claims_extracted") or {"claims": []}
        try:
            cs = ClaimSet.model_validate(claims)
        except ValueError:
            continue
        info["claims"] += len(cs.claims)
        for f in stage_a.run(cs).findings:                                   # re-run on the published version
            info["stage_a_findings"].append({"turn": t["turn"], "code": f.code, "claim": f.claim, "evidence": f.evidence})
        for c in cs.claims:
            key = c.fact_key or (c.record_ref if c.kind == "DATE" else None)
            value = c.date.isoformat() if c.date else (str(c.amount_inr) if c.amount_inr is not None else None)
            if key and value:
                seen_values[(side, key)].append((t["turn"], value, c.text))
            if c.authority_title:
                title = c.authority_title.lower()
                if title in flagged_titles[side]:
                    reused.append({"side": side, "turn": t["turn"], "authority": c.authority_title})
        for f in t.get("flags", []):
            if f["code"] in CITATION_CODES:
                for c in cs.claims:
                    if c.authority_title and c.text == f.get("claim"):
                        flagged_titles[side].add(c.authority_title.lower())

    drift = []
    for (side, key), vals in seen_values.items():
        distinct = {v for _, v, _ in vals}
        if len(distinct) > 1:
            drift.append({"side": side, "fact": key, "statements": [{"turn": tn, "value": v, "text": tx[:200]} for tn, v, tx in vals]})

    for s in SIDES:
        per_side[s]["flag_counts"] = dict(per_side[s]["flag_counts"])
        n = per_side[s]["turns"] or 1
        per_side[s]["unsupported_fact_rate_per_turn"] = round(per_side[s]["unsupported_facts"] / n, 3)
    return {"per_side": per_side, "claim_drift": drift, "flagged_citations_reused": reused}


def transcript_text(transcript: list[dict], with_flags: bool = True, max_chars: int = 6000) -> str:
    rows = []
    for t in transcript:
        flags = ", ".join(sorted({f["code"] for f in t.get("flags", [])})) if with_flags else ""
        rows.append(f"[turn {t['turn']} | {t['speaker']} | {t['stage']}{' | flags: ' + flags if flags else ''}]\n{t['prose'][:max_chars]}")
    return "\n\n".join(rows)


async def run_global(case: UnspoiledCase, transcript: list[dict], services: SourceRegistry, backend: Backend,
                     salt: str) -> dict:
    report = {"deterministic": deterministic_audit(case, transcript, services), "issues": [], "notes": []}
    spec = AgentSpec(role="auditor", system_prompt=prompts.GLOBAL_AUDITOR.format(disclaimer=prompts.DISCLAIMER),
                     output_model=GlobalLLMOutput, cache_salt=salt)
    msg = prompts.GLOBAL_INPUT.format(issues=json.dumps([{"id": i.id, "text": i.text} for i in case.issues], ensure_ascii=False),
                                      transcript=transcript_text(transcript, with_flags=False))
    try:
        out = GlobalLLMOutput.model_validate((await backend.run(spec, msg)).output)
    except AgentError as e:
        report["notes"].append(f"GLOBAL_LLM_FAILED: {str(e)[:300]}")
        return report
    known = {i.id for i in case.issues}
    for ia in out.issues:
        if ia.issue not in known:
            continue
        entry = {"issue": ia.issue}
        for side_name, sf in (("appellant", ia.appellant), ("respondent", ia.respondent)):
            entry[side_name] = {
                "unanswered_points": [x for x in (_strip_verdicts(p, report["notes"]) for p in sf.unanswered_points) if x],
                "contradictions": [{"turns": c.turns, "description": d} for c in sf.contradictions
                                   if (d := _strip_verdicts(c.description, report["notes"]))],
            }
        report["issues"].append(entry)
    return report
