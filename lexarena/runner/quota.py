"""Quota pacing for free-tier keys (BUILD_PLAN Step 13; R-011, R-012; D-049, D-073).

Usage is read from the LLM call log the client already writes (`llm.log_path`: IDs, roles, models, attempts and token
counts, never prompt text). Each logged call is charged to its bucket, the (model, API-key variable) pair its role
uses in config; every attempt is one provider request, cache hits cost nothing. Usage counts over a trailing window
(`runner.quota_window_hours`), which needs no knowledge of each provider's reset hour.

Before a stage starts, `shortfalls` compares what the stage is expected to need (`runner.stage_requests`, per model
role) with what is left in each bucket. Any shortfall pauses the run before the stage begins, so a case is never left
half done for lack of quota. A rate-limit error that still happens mid-stage also pauses (run manager). Buckets are
named by key variable, not key value: two variables holding the same key are counted apart (R-032).
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from lexarena.schemas.config import AppConfig
from lexarena.schemas.run import Stage

CACHE_HIT = "cache_hit"

Bucket = tuple[str, str]  # (model name, API-key variable)


@dataclass(frozen=True)
class Usage:
    requests: int
    tokens: int


def bucket_of(cfg: AppConfig, role: str) -> Bucket | None:
    model = cfg.models.by_role().get(role)
    return None if model is None else (model.name, model.api_key_env)


def usage_since(log_path: Path, cfg: AppConfig, since: datetime) -> dict[Bucket, Usage]:
    requests: dict[Bucket, int] = defaultdict(int)
    tokens: dict[Bucket, int] = defaultdict(int)
    if log_path.is_file():
        for line in log_path.read_text(encoding="utf-8").splitlines():
            try:
                event = json.loads(line)
                when = datetime.fromisoformat(event["ts"])
            except (ValueError, KeyError, TypeError):
                continue  # a torn or foreign line never stops a run
            if when < since or event.get("outcome") == CACHE_HIT:
                continue
            bucket = bucket_of(cfg, event.get("role", ""))
            if bucket is None:
                continue
            requests[bucket] += int(event.get("attempts") or 0)
            tokens[bucket] += int(event.get("input_tokens") or 0) + int(event.get("output_tokens") or 0)
    return {b: Usage(requests[b], tokens[b]) for b in set(requests) | set(tokens)}


def shortfalls(cfg: AppConfig, stage: Stage, used: dict[Bucket, Usage]) -> list[str]:
    """Why the stage cannot start now; empty when every bucket it needs has room."""
    need: dict[Bucket, int] = defaultdict(int)
    for role, count in cfg.runner.stage_requests.for_stage(stage).items():
        bucket = bucket_of(cfg, role)
        if bucket is not None:
            need[bucket] += count
    limits = {(q.model, q.api_key_env): q for q in cfg.runner.quotas}
    problems: list[str] = []
    for bucket, count in sorted(need.items()):
        limit = limits.get(bucket)
        if limit is None:
            continue  # no measured limit for this bucket: nothing to pace against
        spent = used.get(bucket, Usage(0, 0))
        left = limit.requests_per_window - spent.requests
        if left < count:
            problems.append(f"{bucket[0]} on {bucket[1]}: {left} requests left, stage {stage} expects {count}")
        if limit.tokens_per_window is not None and spent.tokens >= limit.tokens_per_window:
            problems.append(f"{bucket[0]} on {bucket[1]}: token budget for the window is spent")
    return problems


def window_start(now: datetime, cfg: AppConfig) -> datetime:
    return now - timedelta(hours=cfg.runner.quota_window_hours)
