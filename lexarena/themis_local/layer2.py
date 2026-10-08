"""THEMIS-LOCAL layer 2 (BUILD_PLAN Step 8; SPEC A2, B4, D4, D5, D8; D-075).

Four jobs, on the verifier model (a different family from the lawyers, temperature 0), read-only, never the judgment:

1. Claim references, in code: a claim that cites a record ID the record does not have is ERR_FACT_NOT_IN_RECORD (no
   model needed: the ID provably does not exist). A statute not visible on the case dates is a warning.
2. Record fidelity (A2), one verifier call: factual statements the record does not contain, and exhibit contents beyond
   `known_contents`. A finding becomes a hard error only if the verifier quotes the argument's own words verbatim (code
   checks it), names record IDs that exist (an exhibit for EXHIBIT_CONTENT_FABRICATED) and is confident enough
   (`themis_local.extraction_min_confidence`); otherwise it is a warning (SPEC D1 point 4: an extraction error never
   rejects an argument). The same call lists the opponent's last points and which were answered (responsiveness:
   a score, never a rejection).
3. Citations (B4, D4): each cited precedent is fetched by ID through the case-scoped tool; one verifier call checks
   every (proposition, ratio) pair. CONTRADICTS is ERR_PRECEDENT_MISATTRIBUTED only with a verbatim quote from the
   ratio; NOT_ADDRESSED and unverifiable citations are warnings. VERIFIED when every cited precedent supports the claim.
   The REFERENCED tier needs an index of authorities cited inside precedents (Q-026) and is not built: such citations
   are UNVERIFIABLE, which never rejects.
4. Repetition (D8): embedding similarity to the agent's own earlier turns; above `repetition_hard_threshold` it is
   ERR_REPEATED_ARGUMENT, above `repetition_warn_threshold` a warning.
"""

from __future__ import annotations

import math
import re
from collections.abc import Callable
from dataclasses import dataclass, field

from lexarena.embedding import Embedder
from lexarena.llm.client import LLMClient
from lexarena.prompts import PromptStore
from lexarena.schemas.agent import DraftClaim
from lexarena.schemas.case import AgentCaseView
from lexarena.schemas.config import AppConfig
from lexarena.schemas.retrieval import PrecedentExcerpt, PrecedentView
from lexarena.schemas.themis import EntailmentBatch, Layer2Review
from lexarena.schemas.transcript import ClaimAssessment, ThemisWarning

ROLE = "verifier"
PRECEDENT_PART = "ratio"
UNMAPPED = "UNMAPPED"
STATUTE_NOT_AVAILABLE = "STATUTE_NOT_AVAILABLE"
WARN_UNVERIFIABLE_CITATION = "WARN_UNVERIFIABLE_CITATION"
WARN_PRECEDENT_NOT_ADDRESSED = "WARN_PRECEDENT_NOT_ADDRESSED"
WARN_REPETITION = "WARN_REPETITION"

PrecedentFetcher = Callable[..., PrecedentExcerpt | PrecedentView | None]


@dataclass(frozen=True)
class Problem:
    """A hard error with what the retry feedback needs (SPEC D7): the code, the exact IDs, a one-line detail."""

    code: str
    detail: str
    record_ids: list[str] = field(default_factory=list)
    claim_ids: list[str] = field(default_factory=list)


@dataclass
class Layer2Result:
    hard_errors: list[Problem] = field(default_factory=list)
    warnings: list[ThemisWarning] = field(default_factory=list)
    assessments: list[ClaimAssessment] = field(default_factory=list)
    responsiveness: float | None = None  # share of the opponent's last points answered; None when there were none
    repetition: float | None = None  # highest similarity to an own earlier turn


def squeeze(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().casefold()


def record_index(case: AgentCaseView) -> dict[str, str]:
    """Every record ID with its kind: STIPULATED, CONTESTED, EXHIBIT, AMOUNT."""
    r = case.record
    return {
        **{f.fact_id: "STIPULATED" for f in r.stipulated_facts},
        **{c.fact_id: "CONTESTED" for c in r.contested_facts},
        **{e.exhibit_id: "EXHIBIT" for e in r.exhibits},
        **{a.amount_id: "AMOUNT" for a in r.amounts},
    }


def render_record(case: AgentCaseView) -> str:
    r = case.record
    lines = [f"[{f.fact_id}] {f.text}" for f in r.stipulated_facts]
    lines += [
        f"[{c.fact_id}] CONTESTED: {c.question} | petitioner: {c.petitioner_version} | respondent: "
        f"{c.respondent_version}"
        for c in r.contested_facts
    ]
    lines += [
        f"[{e.exhibit_id}] EXHIBIT {e.title}; known contents: {' / '.join(e.known_contents)}; nothing else is known"
        for e in r.exhibits
    ]
    lines += [f"[{a.amount_id}] AMOUNT {a.label}: INR {a.value_inr}" for a in r.amounts]
    return "\n".join(lines)


# ---------------------------------------------------------------- 1. claim references (code)


def check_claim_references(
    claims: list[tuple[str, DraftClaim]], record: dict[str, str], visible_statutes: set[str], out: Layer2Result
) -> None:
    for claim_id, claim in claims:
        missing = [rid for rid in claim.record_ids if rid not in record]
        if missing:
            out.hard_errors.append(
                Problem(
                    "ERR_FACT_NOT_IN_RECORD",
                    f"claim {claim_id} cites record items that do not exist: {', '.join(missing)}",
                    missing,
                    [claim_id],
                )
            )
        if claim.statute_id and claim.statute_id not in visible_statutes:
            out.warnings.append(
                ThemisWarning(
                    code=STATUTE_NOT_AVAILABLE,
                    detail=f"claim {claim_id}: {claim.statute_id} is unknown or not in force on the case dates",
                )
            )


# ---------------------------------------------------------------- 2. record fidelity and responsiveness


def review_fidelity(
    llm: LLMClient,
    prompts: PromptStore,
    cfg: AppConfig,
    case: AgentCaseView,
    argument: str,
    opponent: str | None,
    out: Layer2Result,
    *,
    session_id: str,
) -> None:
    ref = cfg.prompts.themis_layer2
    prompt = prompts.render(ref.id, ref.version, record=render_record(case), opponent=opponent or "", argument=argument)
    review = llm.complete_json(role=ROLE, user=prompt, schema=Layer2Review, session_id=session_id).value
    record = record_index(case)
    text = squeeze(argument)
    minimum = cfg.themis_local.extraction_min_confidence
    for issue in review.fidelity_issues:
        ids = [rid for rid in issue.record_ids if rid in record]
        verbatim = bool(issue.quote.strip()) and squeeze(issue.quote) in text
        names_exhibit = issue.kind != "EXHIBIT_CONTENT_FABRICATED" or any(record[i] == "EXHIBIT" for i in ids)
        code = "ERR_FACT_NOT_IN_RECORD" if issue.kind == "NOT_IN_RECORD" else "ERR_EXHIBIT_CONTENT_FABRICATED"
        if verbatim and ids and names_exhibit and issue.confidence >= minimum:
            out.hard_errors.append(Problem(code, f'"{issue.quote.strip()}": {issue.explanation}', ids))
        else:
            out.warnings.append(
                ThemisWarning(
                    code=UNMAPPED,
                    field="record_fidelity",
                    quote=issue.quote or None,
                    detail=f"{issue.kind} not confirmed (verbatim={verbatim}, ids={ids}, "
                    f"confidence={issue.confidence}): {issue.explanation}",
                )
            )
    if opponent and review.opponent_points:
        out.responsiveness = sum(p.addressed for p in review.opponent_points) / len(review.opponent_points)


# ---------------------------------------------------------------- 3. citations


def _ratio_text(got: PrecedentExcerpt | PrecedentView) -> str:
    return got.text if isinstance(got, PrecedentExcerpt) else got.ratio_decidendi


def check_citations(
    llm: LLMClient,
    prompts: PromptStore,
    cfg: AppConfig,
    claims: list[tuple[str, DraftClaim]],
    fetch: PrecedentFetcher,
    out: Layer2Result,
    *,
    session_id: str,
) -> None:
    ratios: dict[str, str] = {}
    pairs: list[tuple[str, str]] = []
    unverifiable: dict[str, list[str]] = {}
    for claim_id, claim in claims:
        for uid in dict.fromkeys(claim.precedent_ids):
            if uid not in ratios:
                got = fetch(uid, PRECEDENT_PART)
                if got is None:
                    unverifiable.setdefault(claim_id, []).append(uid)
                    continue
                ratios[uid] = _ratio_text(got)
            pairs.append((claim_id, uid))
    verdicts: dict[tuple[str, str], tuple[str, str]] = {}
    if pairs:
        text_of = dict(claims)
        items = "\n\n".join(
            f"ITEM claim_id={cid} precedent_uid={uid}\nPROPOSITION: {text_of[cid].text}\nRATIO: {ratios[uid]}"
            for cid, uid in pairs
        )
        ref = cfg.prompts.themis_entailment
        prompt = prompts.render(ref.id, ref.version, items=items)
        batch = llm.complete_json(role=ROLE, user=prompt, schema=EntailmentBatch, session_id=session_id).value
        verdicts = {(v.claim_id, v.precedent_uid): (v.verdict, v.ratio_quote) for v in batch.verdicts}
    for claim_id, claim in claims:
        uids = list(dict.fromkeys(claim.precedent_ids))
        if not uids:
            continue
        results: list[str] = []
        for uid in unverifiable.get(claim_id, []):
            out.warnings.append(
                ThemisWarning(code=WARN_UNVERIFIABLE_CITATION, detail=f"claim {claim_id}: {uid} is not available")
            )
            results.append("UNVERIFIABLE")
        for uid in (u for u in uids if u in ratios):
            verdict, quote = verdicts.get((claim_id, uid), ("NOT_ADDRESSED", ""))
            if verdict == "CONTRADICTS" and quote.strip() and squeeze(quote) in squeeze(ratios[uid]):
                out.hard_errors.append(
                    Problem(
                        "ERR_PRECEDENT_MISATTRIBUTED",
                        f'claim {claim_id}: {uid} holds the opposite: "{quote.strip()}"',
                        claim_ids=[claim_id],
                    )
                )
                results.append("CONTRADICTS")
            elif verdict == "SUPPORTS":
                results.append("SUPPORTS")
            else:
                detail = "contradiction not confirmed by a verbatim quote" if verdict == "CONTRADICTS" else verdict
                out.warnings.append(
                    ThemisWarning(code=WARN_PRECEDENT_NOT_ADDRESSED, detail=f"claim {claim_id}, {uid}: {detail}")
                )
                results.append("NEUTRAL")
        all_support = bool(results) and all(r == "SUPPORTS" for r in results)
        out.assessments.append(
            ClaimAssessment(
                claim_id=claim_id,
                citation_tier="VERIFIED" if all_support else "UNVERIFIABLE",
                entailment="CONTRADICTS" if "CONTRADICTS" in results else "SUPPORTS" if all_support else "NEUTRAL",
            )
        )


# ---------------------------------------------------------------- 4. repetition


def _cosine(a: list[float], b: list[float]) -> float:
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return sum(x * y for x, y in zip(a, b, strict=True)) / norm if norm else 0.0


def check_repetition(embedder: Embedder, argument: str, earlier: list[str], cfg: AppConfig, out: Layer2Result) -> None:
    if not earlier:
        return
    vectors = embedder.embed([argument, *earlier])
    best = max(_cosine(vectors[0], v) for v in vectors[1:])
    out.repetition = best
    t = cfg.themis_local
    if best > t.repetition_hard_threshold:
        out.hard_errors.append(
            Problem("ERR_REPEATED_ARGUMENT", f"the argument repeats an earlier turn of yours (similarity {best:.2f})")
        )
    elif best > t.repetition_warn_threshold:
        out.warnings.append(ThemisWarning(code=WARN_REPETITION, detail=f"similarity {best:.2f} to an earlier turn"))
