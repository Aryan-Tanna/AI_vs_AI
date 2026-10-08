"""The run manager (BUILD_PLAN Step 13; ARCHITECTURE §7; SPEC G1, I3-10; D-049, D-073).

Runs the planned cases strictly one at a time, in date order, each through its stages. Before a stage it checks the
quota; after every stage it writes the ledger, so `go` resumes exactly where a pause or crash left off. It stops:
- PAUSED when a stage's quota is short (checked before the stage starts), a stage exits QUOTA_EXHAUSTED (the stage is
  left PENDING and re-runs on resume; stages are idempotent or cached), or `max_cases` cases finished;
- FAILED when a stage fails, or memory changed during a FROZEN or EMPTY case. A failed case is never skipped: in a
  learning run, later cases must not see memory that missed one (SPEC I3-10).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path

from lexarena import exit_codes
from lexarena.runner.ledger import LedgerStore
from lexarena.runner.memory import FrozenMemoryViolationError, MemoryStore, check_unchanged, stage_allowed
from lexarena.runner.quota import shortfalls, usage_since, window_start
from lexarena.runner.stages import Executor, StageSpec, last_json, render
from lexarena.schemas.config import AppConfig
from lexarena.schemas.run import FINISHED, CaseJob, RunLedger, Stage, StageRecord

TAIL_CHARS = 2000  # literal-ok: how much of a failed stage's stderr the ledger keeps


def _now() -> datetime:
    return datetime.now(UTC)


class RunManager:
    def __init__(
        self,
        cfg: AppConfig,
        store: LedgerStore,
        specs: Mapping[Stage, StageSpec],
        executor: Executor,
        memory: MemoryStore,
        log_path: Path,
        clock: Callable[[], datetime] = _now,
    ) -> None:
        self._cfg = cfg
        self._store = store
        self._specs = specs
        self._exec = executor
        self._memory = memory
        self._log = log_path
        self._clock = clock

    # ------------------------------------------------------------ helpers

    def _finish(self, ledger: RunLedger, status: str, reason: str | None) -> RunLedger:
        ledger = ledger.model_copy(update={"status": status, "pause_reason": reason})
        self._store.save(ledger)
        return ledger

    def _set(self, record: StageRecord, **update: object) -> None:
        for key, value in update.items():
            setattr(record, key, value)

    def _outputs(self, job: CaseJob, ledger: RunLedger) -> dict[str, str]:
        m = ledger.manifest
        values = {
            "case_id": job.case_id,
            "case_dir": self._store.case_dir(job.case_id).as_posix(),
            "run_id": m.run_id,
            "mode": m.mode,
            "seq": str(job.seq),
            "ablations": ",".join(m.ablations),
            "allow_draft_personas": str(m.allow_draft_personas).lower(),
        }
        for r in job.stages:
            if r.status == "DONE":
                values.update(r.outputs)
        return values

    def _run_stage(self, ledger: RunLedger, job: CaseJob, record: StageRecord) -> str | None:
        """Run one stage. Returns None to continue, or the reason to stop (PAUSED:... or FAILED:...)."""
        spec = self._specs[record.stage]
        mode = ledger.manifest.mode
        values = self._outputs(job, ledger)
        if not stage_allowed(record.stage, mode):
            self._set(record, status="SKIPPED", detail=f"{mode} run: memory is never written")
            return None
        if spec.argv is None:
            self._set(record, status="NOT_BUILT", detail="stage not built yet")
            return None
        missing = [n for n in spec.needs if n not in values]
        if missing:
            self._set(record, status="SKIPPED", detail=f"needs {missing} from an earlier stage")
            return None
        argv = render(spec, values)
        if ledger.manifest.dry_run:
            self._set(record, status="DRY", detail="lexarena " + " ".join(argv))
            return None
        short = shortfalls(
            self._cfg, record.stage, usage_since(self._log, self._cfg, window_start(self._clock(), self._cfg))
        )
        if short:
            return f"PAUSED:quota before {record.stage} of {job.case_id}: " + "; ".join(short)
        self._store.case_dir(job.case_id).mkdir(parents=True, exist_ok=True)
        self._set(record, attempts=record.attempts + 1, started_at=self._clock(), detail="lexarena " + " ".join(argv))
        self._store.save(ledger)
        result = self._exec.run(argv)
        if result.code == exit_codes.QUOTA_EXHAUSTED:
            self._set(record, status="PENDING", started_at=None)
            return f"PAUSED:rate limited during {record.stage} of {job.case_id}"
        if result.code != exit_codes.OK:
            self._set(record, status="FAILED", finished_at=self._clock(), detail=result.stderr[-TAIL_CHARS:])
            return f"FAILED:{record.stage} of {job.case_id} exited {result.code}"
        outputs = last_json(result.stdout)
        outputs.update({name: tpl.format(**values) for name, tpl in spec.files.items()})
        self._set(record, status="DONE", finished_at=self._clock(), outputs=outputs)
        return None

    # ------------------------------------------------------------ the run

    def go(self, *, max_cases: int | None = None) -> RunLedger:
        with self._store.locked():
            ledger = self._store.load()
            if ledger.status in ("COMPLETE", "FAILED"):
                return ledger
            ledger = self._finish(ledger, "RUNNING", None)
            finished_now = 0
            for job in ledger.jobs:
                if job.finished:
                    continue
                if max_cases is not None and finished_now >= max_cases:
                    return self._finish(ledger, "PAUSED", f"max_cases {max_cases} reached")
                if job.memory_before is None:
                    job.memory_before = self._memory.snapshot()
                    self._store.save(ledger)
                for record in job.stages:
                    if record.status in FINISHED:
                        continue
                    stop = self._run_stage(ledger, job, record)
                    self._store.save(ledger)
                    if stop is not None:
                        kind, _, reason = stop.partition(":")
                        return self._finish(ledger, kind, reason)
                job.memory_after = self._memory.snapshot()
                try:
                    check_unchanged(ledger.manifest.mode, job.case_id, job.memory_before, job.memory_after)
                except FrozenMemoryViolationError as exc:
                    return self._finish(ledger, "FAILED", str(exc))
                self._store.save(ledger)
                finished_now += 1
            return self._finish(ledger, "COMPLETE", None)


def new_job(seq: int, case_id: str, split: str, decided_on: object, stages: list[str]) -> CaseJob:
    return CaseJob.model_validate(
        {
            "seq": seq,
            "case_id": case_id,
            "split": split,
            "decided_on": decided_on,
            "stages": [
                {
                    "stage": s,
                    "status": "PENDING",
                    "attempts": 0,
                    "started_at": None,
                    "finished_at": None,
                    "detail": None,
                    "outputs": {},
                }
                for s in stages
            ],
            "memory_before": None,
            "memory_after": None,
        }
    )
