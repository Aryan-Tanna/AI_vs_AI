"""Money guard for a run (D-109).

What a run has spent is priced from the LLM call log the client already writes (`llm.log_path`): every logged call
with token counts, priced by its (provider, model) row in `runner.prices`. Cache hits cost nothing. A truncated call is
billed, and its tokens are logged since D-107, so it is counted too.

Pricing is by provider and model, never by model alone: the same Gemini model is free on a direct key and billed on
OpenRouter. A call whose (provider, model) has no price row is UNPRICED, and the run pauses rather than guess (a paid
call that nobody priced is exactly how money leaks).

Before a stage starts, the run manager pauses when spent + that stage's expected cost (`runner.stage_cost_usd`) would
pass `runner.spend_cap_usd`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from lexarena.schemas.config import AppConfig
from lexarena.schemas.run import Stage

CACHE_HIT = "cache_hit"
PER_MILLION = 1_000_000  # literal-ok: prices are quoted per million tokens


@dataclass(frozen=True)
class Spend:
    usd: float
    calls: int
    unpriced: list[str] = field(default_factory=list)  # "provider model" pairs with tokens and no price row


def spent_since(log_path: Path, cfg: AppConfig, since: datetime) -> Spend:
    prices = {(p.provider, p.model): p for p in cfg.runner.prices}
    usd, calls, unpriced = 0.0, 0, set()
    if log_path.is_file():
        for line in log_path.read_text(encoding="utf-8").splitlines():
            try:
                event = json.loads(line)
                when = datetime.fromisoformat(event["ts"])
            except (ValueError, KeyError, TypeError):
                continue  # a torn or foreign line never stops a run
            if when < since or event.get("outcome") == CACHE_HIT:
                continue
            tokens_in = int(event.get("input_tokens") or 0)
            tokens_out = int(event.get("output_tokens") or 0)
            if not tokens_in and not tokens_out:
                continue
            price = prices.get((event.get("provider", ""), event.get("model", "")))
            if price is None:
                unpriced.add(f"{event.get('provider')} {event.get('model')}")
                continue
            usd += (tokens_in * price.input_usd_per_m + tokens_out * price.output_usd_per_m) / PER_MILLION
            calls += 1
    return Spend(usd=usd, calls=calls, unpriced=sorted(unpriced))


def over_budget(cfg: AppConfig, stage: Stage, spent: Spend) -> str | None:
    """Why the stage must not start for money reasons; None when it may."""
    if spent.unpriced:
        return f"calls with no price row in runner.prices: {', '.join(spent.unpriced)}"
    expected = getattr(cfg.runner.stage_cost_usd, stage)
    cap = cfg.runner.spend_cap_usd
    if spent.usd + expected > cap:
        return f"spent ${spent.usd:.2f} + {stage} up to ${expected:.2f} would pass the run's cap ${cap:.2f}"
    return None
