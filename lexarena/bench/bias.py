"""Side-swap test material (CLAUDE.md §8.5): the same transcript and audit with APPELLANT and RESPONDENT labels
exchanged. A judge whose decision follows the label rather than the arguments shows self-preference or label bias.
The run that uses this is part of the ablation runner (Phase 4, Y)."""
import copy
import re

SWAP = {"APPELLANT": "RESPONDENT", "RESPONDENT": "APPELLANT", "appellant": "respondent", "respondent": "appellant",
        "Appellant": "Respondent", "Respondent": "Appellant"}
_RX = re.compile(r"\b(" + "|".join(SWAP) + r")\b")


def _swap_text(s: str) -> str:
    return _RX.sub(lambda m: SWAP[m.group(1)], s)


def swap_transcript(transcript: list[dict]) -> list[dict]:
    out = copy.deepcopy(transcript)
    for t in out:
        t["speaker"] = SWAP[t["speaker"]]
        t["prose"] = _swap_text(t["prose"])
    return out


def swap_report(report: dict) -> dict:
    r = copy.deepcopy(report)
    for issue in r.get("issues", []):
        issue["appellant"], issue["respondent"] = issue.get("respondent"), issue.get("appellant")
    per_side = r.get("deterministic", {}).get("per_side")
    if per_side:
        per_side["APPELLANT"], per_side["RESPONDENT"] = per_side.get("RESPONDENT"), per_side.get("APPELLANT")
    return r
