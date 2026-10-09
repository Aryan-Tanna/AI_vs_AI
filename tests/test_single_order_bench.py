"""One presentation order per persona, alternated (D-093): the shadow bench's cheaper mode."""

from __future__ import annotations

from collections import Counter
from datetime import date
from pathlib import Path

from lexarena.judges.personas import PersonaRegistry
from lexarena.judges.run import Bench
from lexarena.prompts import PromptStore
from lexarena.schemas.bench import ORDERS, PERSONAS
from tests.conftest import PROMPTS_ROOT
from tests.judge_fixtures import CFG, SESSION_ID, client, inputs, opinion_json

SINGLE = CFG.model_copy(
    update={"judging": CFG.judging.model_copy(update={"orders_per_persona": 1, "check_reasons_with_layer1": False})}
)


def approved(tmp_path: Path) -> PersonaRegistry:
    reg = PersonaRegistry(tmp_path / "review", PromptStore(PROMPTS_ROOT), SINGLE.prompts)
    for p in PERSONAS:
        reg.approve(p, by="<owner>", today=date(2000, 1, 2))  # literal-ok: placeholder date
    return reg


def test_one_call_per_persona_decides_and_orders_alternate(tmp_path: Path) -> None:
    llm, judge, verifier = client([opinion_json()] * len(PERSONAS))
    result = Bench(llm, PromptStore(PROMPTS_ROOT), SINGLE, approved(tmp_path)).decide(inputs(), session_id=SESSION_ID)
    assert len(judge.requests) == len(PERSONAS) and verifier.requests == []  # no layer-1 calls either
    assert all(d.status == "DECIDED" and len(d.opinions) == 1 for d in result.decisions)
    assert all(d.order_swap_gap is None for d in result.decisions)
    used = Counter(d.opinions[0].order for d in result.decisions)
    assert set(used) == set(ORDERS)  # neither side is always read first
    assert result.verdict.status == "DECIDED"


def test_the_order_given_to_each_persona_flips_with_the_case() -> None:
    from lexarena.judges.run import single_orders

    a, b = single_orders("CASE_A"), single_orders("CASE_B")
    assert len(a) == len(b) == len(PERSONAS)
    flipped = single_orders("CASE_A", flip=True)
    assert [o for o in flipped] != a
    assert single_orders("CASE_A") == a  # deterministic
