"""Run configuration. Override any field with a LEX_* environment variable or a .env file."""
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parent.parent


class RoleModel(BaseModel):
    model: str                      # Claude Code model alias or full ID ("haiku", "sonnet", "opus", ...)
    max_turns: int = 12             # agent-loop turns (tool round trips) per call
    thinking: bool = True           # extended thinking; off for mechanical roles (extraction, Stage B) to save usage


def _default_roles() -> dict[str, RoleModel]:
    # Everything runs on one Claude subscription, so "different model family for judges" (CLAUDE.md §7.3)
    # is approximated with a different Claude model. Opus drains the 5-hour window fastest.
    return {
        "smoke": RoleModel(model="haiku", max_turns=4),
        "baseline": RoleModel(model="sonnet", max_turns=4),
        "advocate": RoleModel(model="sonnet", max_turns=12),
        "judge": RoleModel(model="opus", max_turns=12),
        "extractor": RoleModel(model="haiku", max_turns=6, thinking=False),   # structured output may need a retry turn
        "verifier": RoleModel(model="haiku", max_turns=4, thinking=False),
        "reflector": RoleModel(model="sonnet", max_turns=10),
    }


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="LEX_", env_file=".env", extra="ignore")

    data_dir: Path = ROOT / "data"
    mode: Literal["eval", "live"] = "eval"      # eval: closed, cutoff-respecting sources; live: everything incl. web search
    sources_file: Path = ROOT / "config" / "sources.yaml"
    public_db_dir: Path = ROOT / "public_db"
    runs_dir: Path = ROOT / "runs"
    roles: dict[str, RoleModel] = Field(default_factory=_default_roles)

    # Session pacing (Claude Pro/Max: 5-hour window + weekly cap, shared with claude.ai)
    stop_at_utilization: float = 0.85   # stop claiming new jobs once any window is this full
    max_session_hours: float = 4.75     # hard cap for a single `run` without --wait
    reset_buffer_s: int = 120           # wait this long past a reported reset before resuming
    unknown_reset_wait_s: int = 1800    # if the CLI reports a limit without a reset time
    max_job_attempts: int = 3           # non-limit failures before a job is marked failed

    allow_api_key: bool = False         # refuse to run if ANTHROPIC_API_KEY would bill the API instead

    @property
    def reference_path(self) -> Path:
        return self.data_dir / "canonical" / "reference_cases.jsonl"

    @property
    def index_dir(self) -> Path:
        return self.data_dir / "index"

    @property
    def state_dir(self) -> Path:
        return self.data_dir / "state"

    @property
    def jobs_db(self) -> Path:
        return self.state_dir / "jobs.sqlite3"

    @property
    def ledger_path(self) -> Path:
        return self.state_dir / "usage_ledger.jsonl"

    @property
    def cache_dir(self) -> Path:
        return self.data_dir / "cache" / "agent"

    @property
    def sandbox_dir(self) -> Path:
        # Empty working directory for every agent: nothing on disk is reachable from it.
        return self.data_dir / "sandbox"

    def role(self, name: str) -> RoleModel:
        return self.roles[name]
