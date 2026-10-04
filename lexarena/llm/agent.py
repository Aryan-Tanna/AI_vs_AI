"""Backend-neutral agent types. Runtime code depends on these, never on the SDK directly."""
from dataclasses import dataclass, field
from typing import Any, Protocol

from pydantic import BaseModel


@dataclass
class AgentSpec:
    role: str                                   # key into Settings.roles; also selects the tool allowlist
    system_prompt: str
    tools: list[Any] = field(default_factory=list)   # SdkMcpTool objects built by lexarena.tools.registry
    output_model: type[BaseModel] | None = None      # structured final output, validated with pydantic
    cache_salt: str = ""                        # e.g. case_uid + data version; tool results depend on it
    model: str | None = None                    # override Settings.roles[role].model
    max_turns: int | None = None


@dataclass
class AgentResult:
    output: dict | None                         # validated structured output (output_model.model_dump())
    text: str
    num_turns: int
    usage: dict
    cost_usd: float | None                      # API-equivalent cost reported by the CLI; not billed on a subscription
    trace: list[dict]                           # every tool call and result, for audit and replay
    session_id: str
    model: str | None
    cached: bool = False

    def to_dict(self) -> dict:
        return self.__dict__.copy()


class UsageLimitReached(Exception):
    """The subscription window (5-hour or weekly) is exhausted. The job must be released, not failed."""

    def __init__(self, resets_at: int | None, limit_type: str | None, detail: str = ""):
        self.resets_at = resets_at
        self.limit_type = limit_type
        super().__init__(f"usage limit reached ({limit_type or 'unknown'}), resets_at={resets_at} {detail}".strip())


class AgentError(Exception):
    """A non-limit failure (bad output, auth, max turns). Counts as a job attempt."""


class Backend(Protocol):
    async def run(self, spec: AgentSpec, prompt: str) -> AgentResult: ...
