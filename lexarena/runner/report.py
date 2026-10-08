"""The run report (BUILD_PLAN Step 13; SPEC G1, G2; D-073): what ran, the proof that a frozen run wrote no memory,
quota use, and the evaluation metrics over the cases evaluated so far, in run order. JSON for tools, Markdown for
people. Nothing in it is fed back into any agent, THEMIS or judge."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

from lexarena.evaluator.report import EvaluationReport, evaluation_report
from lexarena.schemas.base import StoredModel
from lexarena.schemas.config import AppConfig
from lexarena.schemas.evaluation import CaseOutcome
from lexarena.schemas.run import RunLedger, RunManifest

OUTCOME = "outcome"
SHORT_HASH = 12  # literal-ok: display length of a hash


class MemoryProof(StoredModel):
    mode: str
    cases_checked: int
    unchanged: bool
    snapshots: list[str]
    reflect_runs: int


class RunReport(StoredModel):
    manifest: RunManifest
    status: str
    pause_reason: str | None
    cases: int
    cases_finished: int
    stage_status: dict[str, dict[str, int]]
    memory: MemoryProof
    quota_used: dict[str, dict[str, int]]
    evaluation: EvaluationReport
    notes: list[str]


def _outcomes(ledger: RunLedger) -> list[CaseOutcome]:
    out: list[CaseOutcome] = []
    for job in ledger.jobs:
        path = job.record("EVALUATE").outputs.get(OUTCOME) if "EVALUATE" in ledger.manifest.stages else None
        if path and Path(path).is_file():
            out.append(CaseOutcome.model_validate_json(Path(path).read_text(encoding="utf-8")))
    return out


def build_report(ledger: RunLedger, cfg: AppConfig, quota_used: dict[str, dict[str, int]]) -> RunReport:
    stages: dict[str, Counter[str]] = {s: Counter() for s in ledger.manifest.stages}
    for job in ledger.jobs:
        for r in job.stages:
            stages[r.stage][r.status] += 1
    checked = [j for j in ledger.jobs if j.memory_before is not None and j.memory_after is not None]
    snapshots = sorted({s for j in checked for s in (j.memory_before, j.memory_after) if s is not None})
    reflect_runs = sum(r.stage == "REFLECT" and r.status == "DONE" for j in ledger.jobs for r in j.stages)
    notes = []
    if any(r.stage == "SESSION" and r.status == "NOT_BUILT" for j in ledger.jobs for r in j.stages):
        notes.append("SESSION is not built yet (Step 9): no bench verdicts, so no case could be evaluated")
    if ledger.manifest.dry_run:
        notes.append("dry run: stages were planned and recorded, nothing was executed")
    return RunReport(
        manifest=ledger.manifest,
        status=ledger.status,
        pause_reason=ledger.pause_reason,
        cases=len(ledger.jobs),
        cases_finished=sum(j.finished for j in ledger.jobs),
        stage_status={s: dict(c) for s, c in stages.items()},
        memory=MemoryProof(
            mode=ledger.manifest.mode,
            cases_checked=len(checked),
            unchanged=all(j.memory_before == j.memory_after for j in checked),
            snapshots=snapshots,
            reflect_runs=reflect_runs,
        ),
        quota_used=quota_used,
        evaluation=evaluation_report(_outcomes(ledger), cfg.evaluation, cfg.seed),
        notes=notes,
    )


def _fmt(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.3f}"
    if isinstance(value, tuple):
        return "[" + ", ".join(_fmt(v) for v in value) + "]"
    return str(value)


def to_markdown(report: RunReport, ledger: RunLedger) -> str:
    m = report.manifest
    lines = [
        f"# Run {m.run_id}",
        "",
        f"- status: **{report.status}**" + (f" ({report.pause_reason})" if report.pause_reason else ""),
        f"- mode: {m.mode}; ablations: {', '.join(m.ablations) or 'none'}; dry run: {m.dry_run}",
        f"- code {m.git_sha}; config {m.config_version} ({m.config_sha256[:SHORT_HASH]})",
        f"- cases: {report.cases_finished} of {report.cases} finished",
        "",
        "## Cases (run order)",
        "",
        "| # | case | split | " + " | ".join(m.stages) + " | memory unchanged |",
        "| --- | --- | --- | " + " | ".join("---" for _ in m.stages) + " | --- |",
    ]
    for job in ledger.jobs:
        same = "-" if job.memory_after is None else ("yes" if job.memory_before == job.memory_after else "**NO**")
        cells = " | ".join(job.record(s).status for s in m.stages)
        lines.append(f"| {job.seq} | {job.case_id} | {job.split} | {cells} | {same} |")
    mem = report.memory
    lines += [
        "",
        "## Memory",
        "",
        f"{mem.mode} run: {mem.cases_checked} cases checked; snapshots {mem.snapshots or ['-']}; "
        f"unchanged: **{mem.unchanged}**; reflection ran {mem.reflect_runs} times.",
        "",
        "## Quota used in the window",
        "",
        *(
            f"- {bucket}: {use['requests']} requests, {use['tokens']} tokens"
            for bucket, use in report.quota_used.items()
        ),
        "",
        "## Evaluation",
        "",
        f"{report.evaluation.cases} evaluated cases; bootstrap {report.evaluation.bootstrap_resamples} resamples, "
        f"level {report.evaluation.confidence_level}, seed {report.evaluation.seed}.",
    ]
    for sub in report.evaluation.subsets:
        lines += [
            "",
            f"### {sub.subset} ({sub.cases} cases; {sub.unstable_verdicts} unstable; {sub.mixed_outcomes} mixed)",
            "",
            "| level | system | predicted / eligible | accuracy | CI | balanced acc. | macro-F1 |",
            "| --- | --- | --- | --- | --- | --- | --- |",
        ]
        for level in ("verdict", "issues"):
            rep = getattr(sub, level)
            for s in rep.scores:
                lines.append(
                    f"| {level} | {s.system} | {s.predicted} / {s.eligible} | {_fmt(s.accuracy)} | "
                    f"{_fmt(s.accuracy_ci)} | {_fmt(s.balanced_accuracy)} | {_fmt(s.macro_f1)} |"
                )
            c = rep.bench_vs_single_llm
            lines.append(
                f"| {level} | McNemar bench vs single-LLM | {c.pairs} pairs | {c.only_a_right} vs {c.only_b_right} | "
                f"p = {_fmt(c.p_value)} | | |"
            )
    if report.notes:
        lines += ["", "## Notes", "", *(f"- {n}" for n in report.notes)]
    return "\n".join(lines) + "\n"
