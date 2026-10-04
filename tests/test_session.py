"""Session runner tests with a fake backend — no model calls, no subscription usage."""
import asyncio
import json
from pathlib import Path

import pytest

from lexarena.config import Settings
from lexarena.llm.agent import AgentResult, AgentSpec, UsageLimitReached
from lexarena.llm.cache import CachedBackend
from lexarena.orchestrator.handlers import HANDLERS
from lexarena.session.jobs import JobQueue
from lexarena.session.ledger import UsageLedger
from lexarena.session.runner import Stop, run_session, run_until_done
from lexarena.tools.registry import select_tools

EXAMPLE = Path(__file__).resolve().parent.parent / "docs" / "schema" / "example"


class FakeBackend:
    """Returns a valid Turn/BaselinePrediction; raises UsageLimitReached on the calls listed in `limit_on`."""

    def __init__(self, ledger, limit_on=(), utilization=0.1, resets_at=10_000):
        self.calls, self.ledger, self.limit_on = 0, ledger, set(limit_on)
        self.utilization, self.resets_at = utilization, resets_at

    async def run(self, spec: AgentSpec, prompt: str) -> AgentResult:
        self.calls += 1
        if self.calls in self.limit_on:
            raise UsageLimitReached(self.resets_at, "five_hour")
        self.ledger.rate_limit("allowed", self.resets_at, "five_hour", self.utilization)
        out = ({"prose": f"submission {self.calls}", "claims": []} if spec.role == "advocate"
               else {"label": "DISMISSED", "appellant_won": False, "reasons": "r"})
        return AgentResult(out, "", 1, {}, None, [], "s", "fake")


@pytest.fixture
def env(tmp_path):
    s = Settings(data_dir=tmp_path / "data", public_db_dir=tmp_path / "public_db", runs_dir=tmp_path / "runs",
                 reset_buffer_s=0)
    s.public_db_dir.mkdir()
    template = json.loads((EXAMPLE / "unspoiled.json").read_text(encoding="utf-8"))
    (s.public_db_dir / "unspoiled.jsonl").write_text(
        "\n".join(json.dumps({**template, "case_uid": f"PC-{i}"}) for i in (1, 2)), encoding="utf-8")
    ledger = UsageLedger(s.ledger_path)
    return s, ledger, JobQueue(s.jobs_db)


def test_debate_resumes_after_limit_without_repeating_turns(env):
    s, ledger, q = env
    q.enqueue("debate", "debate:t:PC-1", {"case_uid": "PC-1", "run_id": "t"})
    fake = FakeBackend(ledger, limit_on={3}, resets_at=10_000)
    rep = asyncio.run(run_session(q, fake, ledger, HANDLERS, s, clock=lambda: 5_000))
    assert rep.stop is Stop.USAGE_LIMIT and rep.resume_at == 10_000
    assert q.counts()["debate"] == {"pending": 1}

    # Next window (clock past the reset): turns 1–2 come from the checkpoint, only 3–5 are called.
    rep = asyncio.run(run_session(q, fake, ledger, HANDLERS, s, clock=lambda: 20_000))
    assert rep.stop is Stop.QUEUE_EMPTY and rep.done == 1
    assert fake.calls == 6            # 2 ok + 1 limited + 3 resumed
    sealed = json.loads((s.runs_dir / "t" / "PC-1" / "transcript.json").read_text(encoding="utf-8"))
    assert [t["turn"] for t in sealed["turns"]] == [1, 2, 3, 4, 5]
    assert sealed["seal"] == sealed["turns"][-1]["hash"]


def test_blocked_window_starts_no_job(env):
    s, ledger, q = env
    ledger.rate_limit("rejected", 10_000, "five_hour", 1.0)
    q.enqueue("baseline", "b:PC-1", {"case_uid": "PC-1"})
    fake = FakeBackend(ledger)
    rep = asyncio.run(run_session(q, fake, ledger, HANDLERS, s, clock=lambda: 5_000))
    assert rep.stop is Stop.USAGE_LIMIT and fake.calls == 0


def test_stops_between_jobs_near_limit(env):
    s, ledger, q = env
    for uid in ("PC-1", "PC-2"):
        q.enqueue("baseline", f"b:{uid}", {"case_uid": uid})
    fake = FakeBackend(ledger, utilization=0.9)
    rep = asyncio.run(run_session(q, fake, ledger, HANDLERS, s, clock=lambda: 5_000))
    assert rep.stop is Stop.NEAR_LIMIT and rep.done == 1 and q.counts()["baseline"]["pending"] == 1


def test_warning_without_utilization_counts_as_near_limit(tmp_path):
    ledger = UsageLedger(tmp_path / "l.jsonl")
    ledger.rate_limit("allowed", 10_000, "five_hour", None)
    assert ledger.near_limit(0.85, now=5_000) is None
    ledger.rate_limit("allowed_warning", 10_000, "five_hour", None)
    assert ledger.near_limit(0.85, now=5_000) == 10_000
    assert UsageLedger(tmp_path / "l.jsonl").near_limit(0.85, now=5_000) == 10_000   # persisted across processes


def test_run_until_done_sleeps_through_reset(env):
    s, ledger, q = env
    for uid in ("PC-1", "PC-2"):
        q.enqueue("baseline", f"b:{uid}", {"case_uid": uid})
    now = {"t": 5_000.0}
    fake = FakeBackend(ledger, limit_on={2}, resets_at=10_000)

    async def sleep(sec):
        now["t"] += sec

    reps = asyncio.run(run_until_done(q, fake, ledger, HANDLERS, s, sleep=sleep, clock=lambda: now["t"]))
    assert [r.stop for r in reps] == [Stop.USAGE_LIMIT, Stop.QUEUE_EMPTY]
    assert q.counts()["baseline"] == {"done": 2} and now["t"] >= 10_000


def test_cache_hit_skips_backend(env):
    s, ledger, _ = env
    fake = FakeBackend(ledger)
    cached = CachedBackend(fake, s, ledger)
    spec = AgentSpec(role="baseline", system_prompt="x")
    asyncio.run(cached.run(spec, "p"))
    res = asyncio.run(cached.run(spec, "p"))
    assert fake.calls == 1 and res.cached


def test_tool_allowlist_is_enforced():
    with pytest.raises(PermissionError):
        select_tools("advocate", {}, {"read_ground_truth"})
    with pytest.raises(PermissionError):
        select_tools("baseline", {"read_record": object()}, {"read_record"})
    sentinel = object()
    assert select_tools("advocate", {"read_record": sentinel, "read_transcript": sentinel}) == [sentinel, sentinel]


def test_backend_isolation_options(env, monkeypatch):
    pytest.importorskip("claude_agent_sdk")
    from lexarena.llm.claude_code import ClaudeCodeBackend
    s, ledger, _ = env
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    opts = ClaudeCodeBackend(s, ledger).build_options(AgentSpec(role="advocate", system_prompt="x"))
    assert opts.tools == [] and opts.setting_sources == [] and opts.strict_mcp_config
    assert opts.permission_mode == "dontAsk" and opts.cwd == str(s.sandbox_dir)


def test_api_key_is_refused(env, monkeypatch):
    pytest.importorskip("claude_agent_sdk")
    from lexarena.llm.claude_code import ClaudeCodeBackend
    s, ledger, _ = env
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    with pytest.raises(RuntimeError):
        ClaudeCodeBackend(s, ledger)
