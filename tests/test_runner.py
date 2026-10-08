"""The run manager (BUILD_PLAN Step 13; ARCHITECTURE §7; SPEC G1, I3-2, I3-10; D-073). Offline: a scripted executor
stands in for the `lexarena` subprocesses, a fake store for memory."""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from lexarena import exit_codes
from lexarena.config import load_config
from lexarena.runner.ledger import LedgerStore, RunLockedError
from lexarena.runner.manager import RunManager, new_job
from lexarena.runner.plan import CaseRef, PlanRefusedError, assign_splits, check_plan, run_order
from lexarena.runner.quota import shortfalls, usage_since
from lexarena.runner.report import build_report, to_markdown
from lexarena.runner.stages import DEFAULT_SPECS, ExecResult, StageSpec, last_json
from lexarena.schemas.run import STAGES, MemoryMode, RunLedger, RunManifest, Stage
from tests.conftest import CONFIG_V1

CFG = load_config(CONFIG_V1)
NOW = datetime(2000, 1, 2, tzinfo=UTC)  # literal-ok: placeholder clock
D1, D2, D3 = date(2000, 1, 1), date(2000, 2, 1), date(2000, 3, 1)  # literal-ok: placeholder dates

SESSION_SPEC = StageSpec("SESSION", ("session", "run", "--case-id", "{case_id}"))
REFLECT_SPEC = StageSpec("REFLECT", ("reflect", "{session_id}"), needs=("session_id",))


@dataclass
class Script:
    """Answers each call in turn; records every argv."""

    results: list[ExecResult] = field(default_factory=list)
    calls: list[list[str]] = field(default_factory=list)

    def run(self, argv: Sequence[str]) -> ExecResult:
        self.calls.append(list(argv))
        if self.results:
            return self.results.pop(0)
        if argv[0] == "session":
            return ExecResult(0, json.dumps({"session_id": f"{argv[-1]}_R1"}), "")
        return ExecResult(0, "", "")


@dataclass
class Memory:
    value: str = "mem-0"
    bump_on: str | None = None  # a case during which something writes memory
    seen: list[str] = field(default_factory=list)

    def snapshot(self) -> str:
        return self.value


def ledger(
    tmp: Path, mode: MemoryMode = "LEARN", *, dry: bool = False, cases: Sequence[tuple[str, date]] = ()
) -> LedgerStore:
    cases = cases or [("TESTCASE_0002", D2), ("TESTCASE_0001", D1)]
    ordered = run_order([CaseRef(c, "DEV", d) for c, d in cases])
    store = LedgerStore(tmp / "runs", "R1")
    store.save(
        RunLedger(
            manifest=RunManifest(
                run_id="R1",
                created_at=NOW,
                mode=mode,
                ablations=[],
                stages=list(STAGES),
                git_sha="<sha>",
                config_version=CFG.version,
                config_sha256="<hash>",
                dry_run=dry,
            ),
            status="PLANNED",
            pause_reason=None,
            jobs=[new_job(n, r.case_id, r.split, r.decided_on, list(STAGES)) for n, r in enumerate(ordered, 1)],
        )
    )
    return store


def manager(
    store: LedgerStore,
    script: Script,
    memory: Any = None,
    *,
    log: Path | None = None,
    specs: Any = None,
    cfg: Any = CFG,
) -> RunManager:
    specs = specs or {**DEFAULT_SPECS, "SESSION": SESSION_SPEC, "REFLECT": REFLECT_SPEC}
    return RunManager(cfg, store, specs, script, memory or Memory(), log or store.dir / "none.jsonl", clock=lambda: NOW)


def statuses(led: RunLedger) -> list[dict[Stage, str]]:
    return [{r.stage: r.status for r in j.stages} for j in led.jobs]


# ---------------------------------------------------------------- plan


def test_cases_run_in_date_order() -> None:
    refs = [CaseRef("B", "DEV", D2), CaseRef("C", "DEV", D1), CaseRef("A", "DEV", D2)]
    assert [r.case_id for r in run_order(refs)] == ["C", "A", "B"]


@pytest.mark.parametrize(
    ("refs", "mode", "message"),
    [
        ([CaseRef("A", "TRAIN", D1)], "LEARN", "not allowed"),
        ([CaseRef("A", "DEV", D1), CaseRef("A", "DEV", D2)], "LEARN", "twice"),
    ],
)
def test_plans_that_break_a_rule_are_refused(refs: list[CaseRef], mode: MemoryMode, message: str) -> None:
    with pytest.raises(PlanRefusedError, match=message):
        check_plan(refs, mode, CFG.runner)


def test_a_barred_split_is_refused_even_with_no_cases_and_empty_plans_are_refused() -> None:
    with pytest.raises(PlanRefusedError, match="not allowed"):
        check_plan([CaseRef("A", "DEV", D1)], "LEARN", CFG.runner, ["DEV", "TRAIN"])
    with pytest.raises(PlanRefusedError, match="no cases"):
        check_plan([], "FROZEN", CFG.runner, ["DEV"])


def test_learn_runs_never_include_test_cases() -> None:
    phase2 = CFG.runner.model_copy(update={"allowed_splits": ["TRAIN", "VALIDATION", "TEST"]})
    with pytest.raises(PlanRefusedError, match="LEARN"):
        check_plan([CaseRef("A", "TEST", D1)], "LEARN", phase2)
    check_plan([CaseRef("A", "TEST", D1)], "FROZEN", phase2)


def test_splits_by_date_with_dispute_groups_kept_whole() -> None:
    cfg = CFG.splits.model_copy(update={"test_count": 2, "validation_count": 1})
    day = [date(2000, m, 1) for m in range(1, 7)]  # literal-ok: placeholder dates
    dated = [("C1", day[0], "g1"), ("C2", day[1], "g2"), ("C3", day[2], "g3"), ("C4", day[3], "g1"),
             ("C5", day[4], "g4"), ("C6", day[5], "g5")]  # fmt: skip
    split = assign_splits(dated, cfg)
    assert [split[c] for c in ("C5", "C6")] == ["TEST", "TEST"]
    assert split["C4"] == "VALIDATION" and split["C1"] == "VALIDATION"  # C1 follows its group's latest case
    assert split["C2"] == "TRAIN" and split["C3"] == "TRAIN"


# ---------------------------------------------------------------- quota


def _log(path: Path, events: list[dict[str, Any]]) -> Path:
    path.write_text("\n".join(json.dumps(e) for e in events) + "\ntorn {line\n", encoding="utf-8")
    return path


def test_usage_counts_attempts_and_tokens_and_ignores_cache_hits_and_old_calls(tmp_path: Path) -> None:
    recent, old = NOW.isoformat(), (NOW - timedelta(days=2)).isoformat()
    log = _log(
        tmp_path / "log.jsonl",
        [
            {"ts": recent, "role": "judge", "outcome": "ok", "attempts": 2, "input_tokens": 10, "output_tokens": 5},
            {"ts": recent, "role": "judge", "outcome": "cache_hit", "attempts": 0},
            {"ts": old, "role": "judge", "outcome": "ok", "attempts": 1},
            {"ts": recent, "role": "not_a_role", "outcome": "ok", "attempts": 9},
        ],
    )
    used = usage_since(log, CFG, NOW - timedelta(hours=CFG.runner.quota_window_hours))
    bucket = (CFG.models.judge.name, CFG.models.judge.api_key_env)
    assert (used[bucket].requests, used[bucket].tokens) == (2, 15)
    assert len(used) == 1


def test_shortfall_when_a_stage_needs_more_than_is_left(tmp_path: Path) -> None:
    bucket = (CFG.models.judge.name, CFG.models.judge.api_key_env)
    limit = next(q for q in CFG.runner.quotas if (q.model, q.api_key_env) == bucket)
    from lexarena.runner.quota import Usage

    assert shortfalls(CFG, "BASELINE", {}) == []
    assert shortfalls(CFG, "BASELINE", {bucket: Usage(limit.requests_per_window, 0)})
    assert shortfalls(CFG, "EVALUATE", {bucket: Usage(limit.requests_per_window, 0)}) == []  # needs no model


# ---------------------------------------------------------------- the run


def test_dry_run_records_every_stage_and_executes_nothing(tmp_path: Path) -> None:
    store, script = ledger(tmp_path, dry=True), Script()
    led = manager(store, script, specs=DEFAULT_SPECS).go()
    assert led.status == "COMPLETE" and script.calls == []
    assert statuses(led)[0] == {
        "SESSION": "NOT_BUILT",
        "BASELINE": "DRY",
        "EVALUATE": "SKIPPED",
        "REFLECT": "NOT_BUILT",
    }
    assert led.jobs[0].record("BASELINE").detail is not None
    assert "baseline single --case-id TESTCASE_0001" in (led.jobs[0].record("BASELINE").detail or "")


def test_stages_run_in_order_one_case_at_a_time(tmp_path: Path) -> None:
    store, script = ledger(tmp_path), Script()
    led = manager(store, script).go()
    assert led.status == "COMPLETE"
    assert [c[0] for c in script.calls] == ["session", "baseline", "evaluate", "reflect"] * 2
    assert script.calls[0][-1] == "TESTCASE_0001"  # the earlier decision runs first
    assert script.calls[2][2] == "TESTCASE_0001_R1"  # the session's ID reaches the evaluator
    assert led.jobs[0].record("EVALUATE").outputs["outcome"].endswith("TESTCASE_0001/outcome.json")


def test_a_quota_pause_resumes_at_the_same_stage(tmp_path: Path) -> None:
    store = ledger(tmp_path)
    script = Script(
        [ExecResult(0, json.dumps({"session_id": "S1"}), ""), ExecResult(exit_codes.QUOTA_EXHAUSTED, "", "")]
    )
    led = manager(store, script).go()
    assert led.status == "PAUSED" and "rate limited during BASELINE" in (led.pause_reason or "")
    assert statuses(led)[0]["BASELINE"] == "PENDING" and statuses(led)[0]["SESSION"] == "DONE"
    led = manager(store, script).go()
    assert led.status == "COMPLETE"
    assert [c[0] for c in script.calls].count("session") == 2  # once per case, never re-run
    assert led.jobs[0].record("BASELINE").attempts == 2


def test_a_failed_stage_stops_the_run_and_later_cases_never_start(tmp_path: Path) -> None:
    store = ledger(tmp_path)
    script = Script([ExecResult(exit_codes.FAILED, "", "boom")])
    led = manager(store, script).go()
    assert led.status == "FAILED" and statuses(led)[1]["SESSION"] == "PENDING"
    assert led.jobs[0].record("SESSION").detail == "boom"
    assert manager(store, script).go().status == "FAILED" and len(script.calls) == 1


def test_quota_shortfall_pauses_before_the_stage_starts(tmp_path: Path) -> None:
    store, script = ledger(tmp_path), Script()
    tight = CFG.runner.model_copy(
        update={"quotas": [q.model_copy(update={"requests_per_window": 1}) for q in CFG.runner.quotas]}
    )
    cfg = CFG.model_copy(update={"runner": tight})
    led = manager(store, script, cfg=cfg).go()
    assert led.status == "PAUSED" and "quota before SESSION" in (led.pause_reason or "")
    assert script.calls == []


def test_frozen_run_skips_reflection_and_proves_memory_unchanged(tmp_path: Path) -> None:
    store, script = ledger(tmp_path, "FROZEN"), Script()
    led = manager(store, script).go()
    assert led.status == "COMPLETE" and "reflect" not in [c[0] for c in script.calls]
    assert all(s["REFLECT"] == "SKIPPED" for s in statuses(led))
    assert all(j.memory_before == j.memory_after == "mem-0" for j in led.jobs)


class WritingMemory(Memory):
    """Memory that changes as soon as a stage runs: what a leak from a frozen run would look like."""

    def __init__(self, script: Script) -> None:
        super().__init__()
        self._script = script

    def snapshot(self) -> str:
        return f"mem-{len(self._script.calls)}"


@pytest.mark.parametrize("mode", ["FROZEN", "EMPTY"])
def test_a_memory_change_in_a_frozen_or_empty_run_fails_it(tmp_path: Path, mode: MemoryMode) -> None:
    store, script = ledger(tmp_path, mode), Script()
    led = manager(store, script, WritingMemory(script)).go()
    assert led.status == "FAILED" and "memory changed during TESTCASE_0001" in (led.pause_reason or "")
    assert statuses(led)[1]["SESSION"] == "PENDING"


def test_learn_run_may_change_memory(tmp_path: Path) -> None:
    store, script = ledger(tmp_path), Script()
    assert manager(store, script, WritingMemory(script)).go().status == "COMPLETE"


def test_max_cases_pauses_between_cases(tmp_path: Path) -> None:
    store, script = ledger(tmp_path), Script()
    led = manager(store, script).go(max_cases=1)
    assert led.status == "PAUSED" and led.jobs[0].finished and not led.jobs[1].finished


def test_one_manager_per_run(tmp_path: Path) -> None:
    store = ledger(tmp_path)
    with store.locked(), pytest.raises(RunLockedError):
        manager(store, Script()).go()


def test_ledger_refuses_cases_out_of_date_order(tmp_path: Path) -> None:
    store = ledger(tmp_path)
    led = store.load()
    swapped = led.model_dump()
    swapped["jobs"].reverse()
    with pytest.raises(ValueError, match="date order"):
        RunLedger.model_validate(swapped)


def test_last_json_takes_the_final_json_line() -> None:
    assert last_json('noise\n{"session_id": "S1", "x": null}\n') == {"session_id": "S1"}
    assert last_json("no json here") == {}


# ---------------------------------------------------------------- report


def test_report_states_the_memory_proof_and_unbuilt_stages(tmp_path: Path) -> None:
    store = ledger(tmp_path, "FROZEN", dry=True)
    led = manager(store, Script(), specs=DEFAULT_SPECS).go()
    report = build_report(led, CFG, {"<bucket>": {"requests": 1, "tokens": 2}})
    assert report.memory.unchanged and report.memory.reflect_runs == 0 and report.memory.cases_checked == 2
    assert report.evaluation.cases == 0
    assert any("SESSION is not built" in n for n in report.notes)
    md = to_markdown(report, led)
    assert "| 1 | TESTCASE_0001 | DEV | NOT_BUILT | DRY | SKIPPED | SKIPPED | yes |" in md


def test_planted_bug_a_disabled_memory_check_is_caught(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """If the run manager stopped comparing snapshots, the frozen-run test above would still need to fail."""
    import lexarena.runner.manager as m

    monkeypatch.setattr(m, "check_unchanged", lambda *a: None)
    store, script = ledger(tmp_path, "FROZEN"), Script()
    led = manager(store, script, WritingMemory(script)).go()
    assert led.status == "COMPLETE"  # the planted bug lets the leak through ...
    report = build_report(led, CFG, {})
    assert not report.memory.unchanged  # ... and the report's independent proof still exposes it


def test_cli_returns_the_quota_code_on_a_rate_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    from lexarena import cli, cli_judges
    from lexarena.llm.errors import RateLimitedError

    def boom(*_: Any) -> int:
        raise RateLimitedError("quota", retry_after_s=None)

    monkeypatch.setattr(cli_judges, "run", boom)
    assert cli.main(["judges", "personas"]) == exit_codes.QUOTA_EXHAUSTED
