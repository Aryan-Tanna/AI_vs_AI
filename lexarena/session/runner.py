"""Session runner: work through the job queue inside the subscription's usage windows.

One `run_session` call = work until the queue is empty, the window is (nearly) full, or the time cap
is hit. `run_until_done` chains sessions: it sleeps until the reported reset time and continues, so a
long batch (e.g. all train cases) runs unattended across many 5-hour windows.

Jobs are written as a sequence of named steps (`ctx.step`). Each completed step's output is
checkpointed, so a job interrupted mid-debate resumes at the next step in the next window.
"""
import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from lexarena.config import Settings
from lexarena.llm.agent import Backend, UsageLimitReached
from lexarena.session.jobs import Job, JobQueue
from lexarena.session.ledger import UsageLedger

log = logging.getLogger("lexarena.session")


class Stop(str, Enum):
    QUEUE_EMPTY = "queue_empty"
    USAGE_LIMIT = "usage_limit"       # window rejected a call
    NEAR_LIMIT = "near_limit"         # utilization >= stop_at_utilization; stopped between jobs
    TIME_CAP = "time_cap"


@dataclass
class JobContext:
    job: Job
    backend: Backend
    queue: JobQueue
    settings: Settings

    @property
    def steps(self) -> dict[str, Any]:
        return self.job.checkpoint.setdefault("steps", {})

    async def step(self, name: str, fn: Callable[[], Awaitable[Any]]) -> Any:
        """Run fn once per job; on resume return the stored output instead of calling it again."""
        if name in self.steps:
            return self.steps[name]
        out = await fn()
        self.steps[name] = out
        self.queue.save_checkpoint(self.job.id, self.job.checkpoint)
        return out


Handler = Callable[[JobContext], Awaitable[dict]]


@dataclass
class SessionReport:
    stop: Stop
    done: int = 0
    failed: int = 0
    resume_at: float | None = None    # unix time to resume (USAGE_LIMIT / NEAR_LIMIT)
    errors: list[str] = field(default_factory=list)


async def run_session(queue: JobQueue, backend: Backend, ledger: UsageLedger, handlers: dict[str, Handler],
                      settings: Settings, kinds: list[str] | None = None, time_cap: bool = True,
                      clock: Callable[[], float] = time.time) -> SessionReport:
    queue.recover()
    start = clock()
    report = SessionReport(stop=Stop.QUEUE_EMPTY)

    blocked = ledger.blocked_until(clock())
    if blocked is not None:
        report.stop, report.resume_at = Stop.USAGE_LIMIT, blocked
        return report

    while True:
        if time_cap and clock() - start > settings.max_session_hours * 3600:
            report.stop = Stop.TIME_CAP
            return report
        hot = ledger.near_limit(settings.stop_at_utilization, clock())
        if hot is not None:
            report.stop, report.resume_at = Stop.NEAR_LIMIT, hot
            return report
        job = queue.claim_next(kinds or list(handlers))
        if job is None:
            report.stop = Stop.QUEUE_EMPTY
            return report

        if hasattr(backend, "job_key"):
            backend.job_key = job.key
        ctx = JobContext(job, backend, queue, settings)
        try:
            result = await handlers[job.kind](ctx)
            queue.complete(job.id, result)
            report.done += 1
            log.info("done %s", job.key)
        except UsageLimitReached as e:
            queue.release(job.id)
            log.warning("usage limit during %s: %s", job.key, e)
            if e.resets_at:
                ledger.rate_limit("rejected", e.resets_at, e.limit_type or "five_hour", 1.0)
            report.stop = Stop.USAGE_LIMIT
            report.resume_at = e.resets_at or ledger.blocked_until(clock()) or (clock() + settings.unknown_reset_wait_s)
            return report
        except Exception as e:  # noqa: BLE001 — any other failure counts as an attempt
            state = queue.fail(job.id, f"{type(e).__name__}: {e}", settings.max_job_attempts)
            report.failed += state == "failed"
            report.errors.append(f"{job.key}: {type(e).__name__}: {e}")
            log.exception("job %s failed (now %s)", job.key, state)


async def run_until_done(queue: JobQueue, backend: Backend, ledger: UsageLedger, handlers: dict[str, Handler],
                         settings: Settings, kinds: list[str] | None = None,
                         sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
                         clock: Callable[[], float] = time.time,
                         on_pause: Callable[[SessionReport, float], None] | None = None) -> list[SessionReport]:
    """Chain sessions across windows until the queue is empty."""
    reports = []
    while True:
        rep = await run_session(queue, backend, ledger, handlers, settings, kinds, time_cap=False, clock=clock)
        reports.append(rep)
        if rep.stop is Stop.QUEUE_EMPTY:
            return reports
        resume = rep.resume_at
        if resume is None or resume == float("inf"):
            resume = clock() + settings.unknown_reset_wait_s
        wait = max(0.0, resume - clock()) + settings.reset_buffer_s
        if on_pause:
            on_pause(rep, wait)
        await sleep(wait)
