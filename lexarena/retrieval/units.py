"""Index units built from reference cases (CLAUDE.md §8.2): propositions from the ratio, framed issues, and
facts. Retrieval works on propositions and issues by default; facts are for similarity search."""
from dataclasses import dataclass


@dataclass
class Unit:
    unit_id: str
    case_uid: str
    kind: str                 # proposition | issue | facts
    text: str


def units_for(case: dict, facts_chars: int = 1500) -> list[Unit]:
    uid = case["case_uid"]
    out = [Unit(f"{uid}#p{i}", uid, "proposition", t) for i, t in enumerate(case.get("propositions") or []) if t.strip()]
    out += [Unit(f"{uid}#i{i}", uid, "issue", t) for i, t in enumerate(case.get("legal_issues") or []) if t.strip()]
    if case.get("material_facts", "").strip():
        out.append(Unit(f"{uid}#f", uid, "facts", case["material_facts"][:facts_chars]))
    return out
