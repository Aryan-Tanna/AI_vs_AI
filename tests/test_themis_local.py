"""THEMIS-LOCAL gate order and limits (CLAUDE.md §8.3), with fake checkers — no model calls."""
import asyncio
import json

from lexarena.themis.local import Checkers, Finding, verify_turn


class Fake:
    """Turns are {"v": n}; stage_a / stage_b fail for the versions listed."""

    def __init__(self, a_fails=(), b_fails=()):
        self.a_fails, self.b_fails = set(a_fails), set(b_fails)
        self.calls: list[str] = []

    async def extract(self, turn):
        self.calls.append(f"extract{turn['v']}")
        return {"v": turn["v"]}

    def stage_a(self, claims):
        self.calls.append(f"A{claims['v']}")
        return [Finding("ERR_FACT_MISMATCH", "c", "e", "A")] if claims["v"] in self.a_fails else []

    async def stage_b(self, turn, claims):
        self.calls.append(f"B{turn['v']}")
        return [Finding("ERR_MISATTRIBUTED_RATIO", "c", "e", "B")] if turn["v"] in self.b_fails else []

    async def revise(self, turn, findings, n):
        self.calls.append(f"revise{turn['v']}")
        return {"v": turn["v"] + 1}

    def checkers(self):
        return Checkers(self.extract, self.stage_a, self.stage_b, self.revise)


def run(fake):
    return asyncio.run(verify_turn({"v": 0}, fake.checkers()))


def test_clean_turn_runs_a_then_b_once():
    f = Fake()
    r = run(f)
    assert r.status == "PASSED" and f.calls == ["extract0", "A0", "B0"]


def test_stage_a_loop_reextracts_then_b_runs_on_final_version_only():
    f = Fake(a_fails={0, 1})
    r = run(f)
    assert r.status == "PASSED" and r.turn == {"v": 2} and r.stage_a_attempts == 3
    assert f.calls == ["extract0", "A0", "revise0", "extract1", "A1", "revise1", "extract2", "A2", "B2"]


def test_three_stage_a_failures_still_run_stage_b():
    f = Fake(a_fails={0, 1, 2}, b_fails={2})
    r = run(f)
    assert r.status == "FLAGGED_BOTH"
    assert [c for c in f.calls if c.startswith("revise")] == ["revise0", "revise1"]   # 3 attempts = 2 revisions
    assert [c for c in f.calls if c.startswith("B")] == ["B2"]
    assert {x.stage for x in r.flags} == {"A", "B"}


def test_stage_b_failure_is_flagged_not_sent_back():
    f = Fake(b_fails={0})
    r = run(f)
    assert r.status == "FLAGGED_SOFT" and r.turn == {"v": 0}
    assert f.calls == ["extract0", "A0", "B0"]                    # no revision, no second Stage A


def test_resume_does_not_repeat_model_calls():
    store: dict = {}

    async def step(name, fn):
        if name not in store:
            store[name] = json.loads(json.dumps(await fn()))     # checkpoints are JSON
        return store[name]

    f1 = Fake(a_fails={0})
    asyncio.run(verify_turn({"v": 0}, f1.checkers(), step=step))
    f2 = Fake(a_fails={0})
    r = asyncio.run(verify_turn({"v": 0}, f2.checkers(), step=step))
    assert r.status == "PASSED"
    assert not any(c.startswith(("extract", "revise", "B")) for c in f2.calls)   # only code checks re-run
