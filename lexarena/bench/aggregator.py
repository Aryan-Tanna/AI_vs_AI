"""Aggregator (code) and order writer (one LLM call) for the bench (CLAUDE.md §8.5)."""
import json
from collections import Counter

from pydantic import BaseModel, ConfigDict

from lexarena.agents import prompts
from lexarena.bench.personas import ORDER
from lexarena.llm.agent import AgentSpec, Backend


def aggregate(decisions: dict[str, dict]) -> dict:
    """Majority on appellant_won; label = the most common label among the majority (ties broken by persona
    order); issue-wise reasoning kept per judge; dissent recorded."""
    personas = [p for p in ORDER if p in decisions] + [p for p in decisions if p not in ORDER]
    votes = {p: decisions[p]["judgment"]["appellant_won"] for p in personas}
    won = sum(votes.values()) > len(votes) / 2
    majority = [p for p in personas if votes[p] == won]
    counts = Counter(decisions[p]["judgment"]["label"] for p in majority)
    top = max(counts.values())
    label = next(decisions[p]["judgment"]["label"] for p in majority if counts[decisions[p]["judgment"]["label"]] == top)
    issues: dict[str, dict] = {}
    for p in personas:
        for d in decisions[p]["judgment"]["issue_decisions"]:
            issues.setdefault(d["issue"], {})[p] = {k: d.get(k) for k in ("finding", "reasons", "record_refs",
                                                                       "authorities_relied", "disagrees_with_global")}
    dissent = [{"persona": p, "label": decisions[p]["judgment"]["label"], "summary": decisions[p]["judgment"]["summary"]}
               for p in personas if votes[p] != won]
    return {"label": label, "appellant_won": won, "unanimous": not dissent,
            "votes": {p: decisions[p]["judgment"]["label"] for p in personas},
            "issues": dict(sorted(issues.items())), "dissent": dissent,
            "flags": {p: decisions[p]["flags"] for p in personas if decisions[p]["flags"]}}


class Order(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str


async def write_order(aggregated: dict, backend: Backend, salt: str) -> str:
    spec = AgentSpec(role="order_writer", system_prompt=prompts.ORDER_WRITER.format(disclaimer=prompts.DISCLAIMER),
                     output_model=Order, cache_salt=salt)
    out = await backend.run(spec, json.dumps({k: aggregated[k] for k in ("label", "appellant_won", "issues", "dissent")},
                                             ensure_ascii=False))
    text = out.output["text"]
    if not text.startswith("SIMULATED ORDER"):
        text = "SIMULATED ORDER - research simulation, not a real NCLAT order\n\n" + text
    return text
