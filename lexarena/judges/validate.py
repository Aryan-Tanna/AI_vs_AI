"""The judge validator (ARCHITECTURE §5; SPEC I3-6; D-048).

Checks one opinion draft against what the judge was shown, mechanically:
- every framed issue is decided exactly once, and no other issue is;
- every governing rule is a statute or precedent the judge was shown, and every record ID is in the record, so a
  reason can cite only things that exist and are allowed for this case's date and exclusions;
- advocacy scores cover exactly the decided issues;
- the overall result follows from the issue findings: if every issue that upholds a side upholds the same side, the
  overall result must be that side. Mixed findings leave the overall result to the judge, since which issue is
  decisive is a legal judgement code cannot make.

THEMIS layer 1 problems in the judge's stated law are added by the caller (judges/run.py). Problems are fed back once;
whatever survives the revision makes the opinion INVALID and its persona abstains.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from pydantic import ValidationError

from lexarena.schemas.bench import (
    InvalidOpinion,
    IssueAdvocacy,
    IssueDecision,
    JudgeOpinion,
    OpinionDraft,
    PresentationOrder,
)


@dataclass(frozen=True)
class Allowed:
    """What a reason may cite: the case's framed issues, the statutes and precedents the judge was shown, the record."""

    issue_ids: list[str]
    statute_ids: set[str]
    precedent_uids: set[str]
    record_ids: set[str]


def check_opinion(draft: OpinionDraft, allowed: Allowed) -> list[str]:
    problems: list[str] = []
    framed = set(allowed.issue_ids)
    decided = Counter(d.issue_id for d in draft.issue_decisions)
    problems += [f"MISSING_ISSUE {i}: decide this issue" for i in allowed.issue_ids if i not in decided]
    problems += [f"UNKNOWN_ISSUE {i}: not a framed issue" for i in sorted(decided) if i not in framed]
    problems += [f"DUPLICATE_ISSUE {i}: decide each issue once" for i, n in sorted(decided.items()) if n > 1]

    rules = allowed.statute_ids | allowed.precedent_uids
    for d in draft.issue_decisions:
        if not d.governing_rule_ids:
            problems.append(f"NO_GOVERNING_RULE {d.issue_id}: cite the statute or precedent IDs the finding rests on")
        for rid in d.governing_rule_ids:
            if rid not in rules:
                problems.append(f"UNKNOWN_RULE_ID {d.issue_id}: {rid} is not a statute or precedent you were shown")
        for rid in d.record_ids:
            if rid not in allowed.record_ids:
                problems.append(f"UNKNOWN_RECORD_ID {d.issue_id}: {rid} is not in the record")
        for field, text in (("finding", d.finding), ("application", d.application), ("conclusion", d.conclusion)):
            if not text.strip():
                problems.append(f"EMPTY_REASON {d.issue_id}: {field} is empty")

    scored = Counter(a.issue_id for a in draft.advocacy)
    if set(scored) != set(decided) or any(n > 1 for n in scored.values()):
        problems.append("ADVOCACY_MISMATCH: score each decided issue exactly once, for both sides")
    if not draft.overall_reasons.strip():
        problems.append("EMPTY_REASON overall: give the reasons for the overall result")

    upheld = {d.upholds for d in draft.issue_decisions if d.upholds != "NEITHER"}
    if len(upheld) == 1 and draft.overall_result not in upheld:
        [side] = upheld
        problems.append(
            f"RESULT_CONTRADICTS_FINDINGS: every issue you decided for a side upholds {side}, "
            f"but the overall result is {draft.overall_result}"
        )
    return problems


def finalize(
    draft: OpinionDraft, order: PresentationOrder, *, revised: bool, problems: list[str]
) -> JudgeOpinion | InvalidOpinion:
    """A valid opinion, or an InvalidOpinion holding the draft and every problem that remains."""
    if not problems:
        try:
            return JudgeOpinion(
                order=order,
                issue_decisions=[IssueDecision.model_validate(d.model_dump()) for d in draft.issue_decisions],
                overall_result=draft.overall_result,
                overall_reasons=draft.overall_reasons,
                advocacy=[
                    IssueAdvocacy(issue_id=a.issue_id, PETITIONER=a.petitioner, RESPONDENT=a.respondent)
                    for a in draft.advocacy
                ],
                revised=revised,
            )
        except ValidationError as exc:  # a shape the checks above do not cover, e.g. a malformed issue ID
            problems = [f"MALFORMED: {e['loc']}: {e['msg']}" for e in exc.errors()]
    return InvalidOpinion(order=order, revised=revised, problems=problems, draft=draft)
