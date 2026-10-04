"""Common result type for every rule: a status, the computed value, and the reasoning steps."""
import datetime as dt
from dataclasses import dataclass, field
from typing import Any


@dataclass
class RuleResult:
    rule: str                                   # e.g. "LIMITATION_ART137"
    status: str                                 # e.g. WITHIN_LIMITATION, BARRED, MET, NOT_MET
    value: Any = None                           # main computed value (a date, an amount, ...)
    details: dict[str, Any] = field(default_factory=dict)
    steps: list[str] = field(default_factory=list)       # human-readable computation, for agents and the bench
    for_bench: list[str] = field(default_factory=list)   # questions the engine does not decide
    verify: list[str] = field(default_factory=list)      # assumptions still to check against primary sources
    provisions: list[str] = field(default_factory=list)  # canonical provision IDs relied on

    def to_dict(self) -> dict:
        def conv(v):
            if isinstance(v, dt.date):
                return v.isoformat()
            if isinstance(v, dict):
                return {k: conv(x) for k, x in v.items()}
            if isinstance(v, (list, tuple)):
                return [conv(x) for x in v]
            return v
        return conv(self.__dict__.copy())
