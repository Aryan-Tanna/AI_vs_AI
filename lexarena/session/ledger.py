"""Append-only usage ledger. Persists the subscription's rate-limit state across processes and windows.

The Claude CLI emits a rate-limit event (status, utilization, resets_at) per window type: five_hour,
seven_day, seven_day_opus, seven_day_sonnet. We keep the latest event per type and use it to decide
whether to start another job.
"""
import json
import time
from pathlib import Path


class UsageLedger:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.windows: dict[str, dict] = {}       # limit_type -> latest rate-limit event
        if self.path.exists():
            for line in self.path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    self._apply(json.loads(line))

    def _apply(self, ev: dict) -> None:
        if ev.get("event") == "rate_limit":
            self.windows[ev.get("limit_type") or "unknown"] = ev

    def _append(self, ev: dict) -> None:
        ev.setdefault("ts", time.time())
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(ev, ensure_ascii=False) + "\n")
        self._apply(ev)

    def rate_limit(self, status: str, resets_at: int | None, limit_type: str | None,
                   utilization: float | None) -> None:
        self._append({"event": "rate_limit", "status": status, "resets_at": resets_at,
                      "limit_type": limit_type, "utilization": utilization})

    def call(self, role: str, model: str | None, num_turns: int, usage: dict,
             cost_usd: float | None, cached: bool, job_key: str | None = None) -> None:
        self._append({"event": "call", "role": role, "model": model, "num_turns": num_turns,
                      "usage": usage, "cost_usd": cost_usd, "cached": cached, "job": job_key})

    def _live(self, now: float) -> list[dict]:
        """Windows whose reset time is still in the future (or unknown)."""
        return [w for w in self.windows.values() if not w.get("resets_at") or w["resets_at"] > now]

    def blocked_until(self, now: float | None = None) -> float | None:
        """Unix time when a rejected window resets, or None if nothing is blocking."""
        now = time.time() if now is None else now
        rejected = [w for w in self._live(now) if w.get("status") == "rejected"]
        if not rejected:
            return None
        known = [w["resets_at"] for w in rejected if w.get("resets_at")]
        return max(known) if known else float("inf")

    def near_limit(self, threshold: float, now: float | None = None) -> float | None:
        """If any live window's utilization >= threshold, return its reset time (inf if unknown)."""
        now = time.time() if now is None else now
        # The CLI reports utilization only once a window nears its limit; an "allowed_warning" without a
        # number is treated as hot.
        hot = [w for w in self._live(now)
               if (w.get("utilization") or 0) >= threshold
               or (w.get("status") == "allowed_warning" and w.get("utilization") is None)]
        if not hot:
            return None
        known = [w["resets_at"] for w in hot if w.get("resets_at")]
        return max(known) if known else float("inf")

    def summary(self, now: float | None = None) -> dict:
        now = time.time() if now is None else now
        return {k: {"status": w.get("status"), "utilization": w.get("utilization"),
                    "resets_in_min": round((w["resets_at"] - now) / 60, 1) if w.get("resets_at") else None}
                for k, w in self.windows.items()}
